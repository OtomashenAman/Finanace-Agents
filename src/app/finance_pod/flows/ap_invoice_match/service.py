"""The invoice match's own rules: one case per incoming invoice, the receiver's confirmation
becoming a receipt in ERPNext, the requirement's rules, the measures and the weekly review of
held invoices."""

from __future__ import annotations

import statistics
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.common import doc_of, need, policy_values, result
from src.app.finance_pod.flows.ap_invoice_match import agents
from src.app.finance_pod.flows.ap_invoice_match.policy import ApmPolicy
from src.app.finance_pod.flows.ap_invoice_match.results import (
    DuplicateDecision,
    LineByLine,
    ReceiptConfirmed,
)
from src.app.jobs import queue as jobs
from src.app.jobs.queue import JobContext
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseSelectionError
from src.app.service_pod.core.cases.models import (
    LOCKED_STATUSES,
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.spec import StepSpec, StepStatus
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import TaskKind
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

KEY = WorkflowKey.AP_INVOICE_MATCH
REVIEW_JOB = "finance.apm_held_review"


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    bill_id = case.selection.get("bill_id")
    bill = next((b for b in doc.bills or [] if b.id == bill_id), None)
    if bill is None:
        raise CaseSelectionError(f"Invoice {bill_id} isn't in this snapshot.")
    if refresh:
        return
    if bill.doc_status != "Draft" or bill.return_against:
        raise CaseSelectionError(f"{bill_id} isn't an incoming invoice (it's {bill.doc_status}).")
    taken = await session.scalar(
        select(PodCase.id).where(
            PodCase.workflow == KEY,
            PodCase.selection["bill_id"].astext == bill_id,
            PodCase.status != CaseStatus.CANCELLED,
        )
    )
    if taken is not None:
        raise CaseSelectionError(f"{bill_id} already has a matching case.")
    version, values = await policy_values(session, KEY.value, ApmPolicy)
    case.state = {
        **case.state,
        "policy": {"version": version, "values": values.model_dump(mode="json")},
    }


def draft_bills_without_case(doc: SnapshotDocument, taken: set[str]) -> list[str]:
    return [
        b.id for b in doc.bills or []
        if b.doc_status == "Draft" and b.return_against is None and b.id not in taken
    ]  # fmt: skip


async def after_receipt(c: Ctx, step: StepSpec) -> str | None:
    """3.6.2: the receiver's confirmation posts the receipt to ERPNext (it authorises exactly
    this posting); a fresh snapshot verifies it before the re-match."""
    if c.request is None:
        return None
    confirmed = need(c, "3.6.2.a", ReceiptConfirmed)
    doc = await doc_of(c)
    bill = agents.bill_of(c, doc)
    on_invoice = {ln.order_line_id for ln in bill.lines if ln.order_line_id}
    unknown = [ln.order_line_id for ln in confirmed.lines if ln.order_line_id not in on_invoice]
    if unknown:
        raise CaseActionError(f"Not lines of this invoice's PO: {', '.join(unknown)}.")
    if not any(ln.received_qty > 0 for ln in confirmed.lines):
        raise CaseActionError("Nothing received: record the receipt when the goods arrive.")
    task = await tasks.add_task(
        c.session, c.case,
        TaskCreate(kind=TaskKind.CREATE_PURCHASE_RECEIPT,
                   reference=f"{c.case.reference} {confirmed.received_on.isoformat()}",
                   instructions={"doc": agents.receipt_doc(c, doc, bill, confirmed)}),
        c.user.id, approved_by_step=True,
    )  # fmt: skip
    try:
        await tasks.post_now(c.session, c.access, task, c.case, c.request)
    except tasks.TaskRefusedError as exc:
        return f"receipt queued; posting to ERPNext failed ({exc.message}): post it again"
    return f"receipt posted to ERPNext as {task.external_txn_id}"


# --- rules ---------------------------------------------------------------------------------


async def duplicate_rule(c: Ctx) -> str | None:
    """AP3.R2 Duplicates blocked by number, vendor, amount."""
    decision = result(c, "3.2.2.b", DuplicateDecision)
    if decision is None or not decision.blocked:
        return None
    cleared = any(
        t.subject == "Possible duplicate" and t.status == ReviewTaskStatus.RESOLVED
        for t in c.children.review_tasks
    )
    return None if cleared else "A possible duplicate blocks this invoice (AP3.R2)."


# --- measures -------------------------------------------------------------------------------


async def first_pass_rate(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP3.M1 First-pass match rate (% matched at the first classification)."""
    routed = [c.state["_first_outcome"] for c in cases if "_first_outcome" in c.state]
    if not routed:
        return None
    first = sum(1 for r in routed if r != "exception")
    return Decimal(str(round(100 * first / len(routed), 1)))


async def exception_ageing(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP3.M2 Exception ageing (days, median, of the invoices still held)."""
    held = [c for c in cases if c.state.get("_first_outcome") == "exception"
            and c.status not in LOCKED_STATUSES and c.status != CaseStatus.APPROVED]  # fmt: skip
    if not held:
        return None
    now = utcnow()
    return Decimal(str(round(statistics.median((now - c.created_at).days for c in held), 1)))


async def duplicates_stopped(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP3.M3 Duplicates stopped (invoices the duplicate guard blocked)."""
    if not cases:
        return None
    rows = await session.scalars(
        select(PodCaseStep.result).where(
            PodCaseStep.case_id.in_([c.id for c in cases]),
            PodCaseStep.l5_code == "3.2.2.b",
            PodCaseStep.status == StepStatus.DONE,
        )
    )
    return Decimal(sum(1 for r in rows if r and r.get("blocked")))


# --- AP3.R3 Held invoices reviewed weekly ----------------------------------------------------


@jobs.daily(REVIEW_JOB)
@jobs.handler(REVIEW_JOB)
async def review_held(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    """Every held invoice untouched for the policy's days gets a review task (an owner and a
    date), so none ages unseen (AP3.P3)."""
    held = list(
        await session.scalars(
            select(PodCase).where(PodCase.workflow == KEY, PodCase.status == CaseStatus.DRAFT)
        )
    )
    now = utcnow()
    for case in held:
        if case.state.get("_first_outcome") != "exception":
            continue
        days = int((case.state.get("policy", {}).get("values") or {}).get("held_review_days", 7))
        if now - case.updated_at < timedelta(days=days):
            continue
        open_review = await session.scalar(
            select(PodReviewTask.id).where(
                PodReviewTask.case_id == case.id,
                PodReviewTask.subject == "Weekly review",
                PodReviewTask.status == ReviewTaskStatus.OPEN,
            )
        )
        if open_review is None:
            session.add(
                PodReviewTask(
                    case_id=case.id, kind=ReviewTaskKind.OTHER, subject="Weekly review",
                    detail=(f"This invoice has been held for {(now - case.updated_at).days} days "
                            "without a change: chase the vendor, the buyer or the receiver."),
                    blocking=False, created_by=None,
                )
            )  # fmt: skip


def held_lines(c: Ctx) -> list[str]:
    lines = result(c, "3.4.1.a", LineByLine)
    return [ln.item_code for ln in (lines.lines if lines else []) if ln.status != "match"]
