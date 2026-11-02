"""Vendor onboarding's own rules: opening, the call-back check, the guardrails, the supplier
it creates in ERPNext once released, its measure, and the AP analyst's manual reading."""

from __future__ import annotations

import contextlib
import re
import statistics
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMProvider
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.common import need, policy_of, policy_values, result
from src.app.finance_pod.flows.ap_vendor_onboarding.agents import secure
from src.app.finance_pod.flows.ap_vendor_onboarding.policy import VndPolicy
from src.app.finance_pod.flows.ap_vendor_onboarding.results import (
    CallBack,
    DocumentsRead,
    ManualDetails,
)
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseSelectionError
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskKind,
)
from src.app.service_pod.core.messaging.models import ArtifactChannel, PodArtifact, PodMessage
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.steps.spec import StepSpec
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import ActionSpec, Ctx

KEY = WorkflowKey.AP_VENDOR_ONBOARDING
_EMAIL = TypeAdapter(EmailStr)
BANK_WORDS = re.compile(
    r"(?i)\b(iban|routing|aba|swift|bic|account (?:no|number)|bank details|new bank|"
    r"changed? (?:our )?bank)\b|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b|\b\d{9}\b"
)


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    name = str(case.selection.get("vendor_name") or "").strip()
    email = str(case.selection.get("contact_email") or "").strip()
    if not name:
        raise CaseSelectionError("Name the vendor to onboard.")
    try:
        _EMAIL.validate_python(email)
    except ValidationError as exc:
        raise CaseSelectionError("Give the vendor's contact email for the invitation.") from exc
    if not refresh:  # later snapshots hold the supplier this case created
        if name.casefold() in {v.name.casefold() for v in doc.vendors or []}:
            raise CaseSelectionError(f"{name} is already in the vendor master.")
        version, values = await policy_values(session, KEY.value, VndPolicy)
        case.state = {
            **case.state,
            "policy": {"version": version, "values": values.model_dump(mode="json")},
        }


async def after_call_back(c: Ctx, step: StepSpec) -> str | None:
    """1.5.2.a: the vendor confirmed the account the letter states (its last 4 digits)."""
    call = need(c, "1.5.2.a", CallBack)
    account = secure(c).get("account_number") or ""
    if not account.endswith(call.account_last4):
        raise CaseActionError(
            "The last 4 digits confirmed on the call don't match the bank letter: record the "
            "call-back as failed instead."
        )
    return f"bank confirmed by phone with {call.spoke_with}"


# --- rules ---------------------------------------------------------------------------------


async def bank_from_portal_rule(c: Ctx) -> str | None:
    """AP1.G2 Bank changes never accepted by email: the bank letter came through the portal."""
    docs = result(c, "1.5.1.b", DocumentsRead)
    if docs is None:
        return None
    letter = await c.session.get(PodArtifact, docs.bank.document_id)
    if letter is None or letter.channel != ArtifactChannel.VENDOR_PORTAL:
        return "Bank details are only taken from the vendor portal, never from email (AP1.G2)."
    return None


# --- after the release: the supplier in ERPNext ---------------------------------------------


async def create_supplier(c: Ctx) -> None:
    """Released (both people approved): queue the supplier and post it right away. If ERPNext
    refuses, the task stays proposed for a person to post again."""
    if c.request is None:
        return
    docs = need(c, "1.5.1.b", DocumentsRead)
    numbers = secure(c)
    group = policy_of(c.case, VndPolicy).supplier_group
    supplier = {
        "supplier_name": c.case.selection["vendor_name"],
        "supplier_group": group,
        "supplier_type": "Company",
        "tax_id": numbers.get("tax_id"),
        "email_id": c.case.selection["contact_email"],  # ERPNext makes it the primary contact
    }
    task = await tasks.add_task(
        c.session, c.case,
        TaskCreate(kind=TaskKind.CREATE_SUPPLIER, reference=c.case.selection["vendor_name"],
                   instructions={"doc": supplier, "bank_fingerprint": docs.bank.fingerprint}),
        c.user.id,
    )  # fmt: skip
    # If ERPNext refuses, the task stays proposed: a person posts it again from the case
    with contextlib.suppress(tasks.TaskRefusedError):
        await tasks.post_now(c.session, c.access, task, c.case, c.request)


# --- reading a reply: bank details by email are refused --------------------------------------


async def read_reply(
    session: AsyncSession, case: PodCase, message: PodMessage, llm: LLMProvider
) -> None:
    """AP1.G2 / AP1.P3: a reply that carries bank details raises a blocking review task; the
    details are never taken from it."""
    if not BANK_WORDS.search(f"{message.subject}\n{message.body}"):
        return
    session.add(
        PodReviewTask(
            case_id=case.id, kind=ReviewTaskKind.OTHER, subject="Bank details by email",
            detail=(f"The reply from {message.to_email or 'the vendor'} looks like it carries bank "
                    "details. They are never taken from email: ask the vendor to use the portal "
                    "link, and check whether someone is impersonating them."),
            blocking=True, created_by=None,
        )
    )  # fmt: skip


# --- measure --------------------------------------------------------------------------------


async def setup_time(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP1.M3 Vendor set-up time (days, median): opened -> supplier verified in ERPNext."""
    if not cases:
        return None
    rows = await session.execute(
        select(PodPostingTask.case_id, PodPostingTask.verified_at).where(
            PodPostingTask.case_id.in_([c.id for c in cases]),
            PodPostingTask.kind == TaskKind.CREATE_SUPPLIER,
            PodPostingTask.status == TaskStatus.VERIFIED,
        )
    )
    opened = {c.id: c.created_at for c in cases}
    days = [(at - opened[cid]).total_seconds() / 86400 for cid, at in rows.all() if at]
    return Decimal(str(round(statistics.median(days), 1))) if days else None


# --- the AP analyst reads a scanned document --------------------------------------------------


def _guard_manual(c: Ctx) -> str | None:
    if c.case.status != CaseStatus.DRAFT:
        return "The documents are read while the onboarding is open."
    if not c.access.holds(Cap.AP_ANALYST.value, c.case.entity_id):
        return "Only an AP analyst can enter a document's details."
    return None


async def _enter_manually(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, ManualDetails)  # noqa: S101
    for doc_id in (p.tax_document_id, p.bank_document_id):
        doc = await c.session.get(PodArtifact, doc_id)
        if doc is None or doc.case_id != c.case.id or doc.channel != ArtifactChannel.VENDOR_PORTAL:
            raise CaseActionError("Only documents the vendor uploaded through the portal count.")
    c.case.state = {**c.case.state, "manual_read": p.model_dump(mode="json")}
    return "Entered the vendor's documents by hand (scanned, no text)", True


def actions() -> dict[str, ActionSpec]:
    from src.app.service_pod.core.cases.service import ActionSpec

    return {"enter_vendor_details": ActionSpec(ManualDetails, _guard_manual, _enter_manually)}
