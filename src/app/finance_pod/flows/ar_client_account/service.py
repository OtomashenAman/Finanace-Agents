"""Client account set-up's own rules: opening, the portal invitation, the credit
controller's decision, the customer it creates in the ERP once released, the rules and
measures, and the daily limit review."""

from __future__ import annotations

import contextlib
import statistics
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.common import cents, doc_of, need, policy_of, policy_values, result
from src.app.finance_pod.flows.ar_client_account import agents
from src.app.finance_pod.flows.ar_client_account.policy import ArcPolicy
from src.app.finance_pod.flows.ar_client_account.results import (
    Application,
    ClientCreated,
    CreditDecision,
    CreditProposal,
    DocumentsUploaded,
)
from src.app.jobs import queue as jobs
from src.app.jobs.queue import JobContext
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseSelectionError
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from src.app.service_pod.core.messaging.models import ArtifactChannel, PodArtifact
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.steps.spec import StepSpec
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import ActionSpec, Ctx

KEY = WorkflowKey.AR_CLIENT_ACCOUNT
_EMAIL = TypeAdapter(EmailStr)
REVIEW = "Credit limit review"
DAILY_JOB = "finance.arc_limit_review"


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    name = str(case.selection.get("client_name") or "").strip()
    email = str(case.selection.get("contact_email") or "").strip()
    if not name:
        raise CaseSelectionError("Name the client.")
    try:
        _EMAIL.validate_python(email)
    except ValidationError as exc:
        raise CaseSelectionError("Give the client's contact email for the invitation.") from exc
    unknown = set(case.selection) - {"client_name", "contact_email"}
    if unknown:
        raise CaseSelectionError(f"Unknown selection: {', '.join(sorted(unknown))}.")
    if not refresh:  # later snapshots hold the client this case created
        if name.casefold() in {c.name.casefold() for c in doc.clients or []}:
            raise CaseSelectionError(f"{name} is already a client.")
        others = await session.scalars(
            select(PodCase).where(
                PodCase.workflow == KEY,
                PodCase.status.in_([CaseStatus.DRAFT, CaseStatus.APPROVED]),
                PodCase.id != case.id,
            )
        )
        same = next(
            (o for o in others if str(o.selection.get("client_name", "")).casefold()
             == name.casefold()),
            None,
        )  # fmt: skip
        if same is not None:
            raise CaseSelectionError(f"{name} already has an application open ({same.reference}).")
        version, values = await policy_values(session, KEY.value, ArcPolicy)
        case.state = {
            **case.state,
            "policy": {"version": version, "values": values.model_dump(mode="json")},
        }


# --- the portal invitation (an action: the PDF's 1.1.1 starts with the client) ------------


class InvitePayload(BaseModel):
    pass


def _guard_invite(c: Ctx) -> str | None:
    if c.case.status != CaseStatus.DRAFT:
        return "The invitation is sent while the application is open."
    if not c.access.holds_any({Cap.CREDIT_CONTROLLER.value, Cap.BILLING_ANALYST.value},
                              c.case.entity_id):  # fmt: skip
        return "A credit controller or billing analyst invites the client."
    return None


async def _invite(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    email = await agents.invite(c)
    return f"Drafted the portal invitation to {email} (a person sends it)", False


def actions() -> dict[str, ActionSpec]:
    from src.app.service_pod.core.cases.service import ActionSpec

    return {"invite_client": ActionSpec(InvitePayload, _guard_invite, _invite)}


# --- 1.2.2 the credit controller's decision ------------------------------------------------


async def after_decision(c: Ctx, step: StepSpec) -> str | None:
    """1.2.2: a limit above the agent's proposal says why; a decline closes the case."""
    decision = need(c, "1.2.2.a", CreditDecision)
    proposal = need(c, "1.2.1.b", CreditProposal)
    policy = policy_of(c.case, ArcPolicy)
    if decision.decision == "decline":
        c.case.status = CaseStatus.CANCELLED
        return f"declined: {decision.reason}"
    if decision.decision == "deposit_only":
        return "deposit only: no credit"
    assert decision.credit_limit is not None and decision.terms_days is not None  # noqa: S101
    if decision.terms_days not in policy.terms_days:
        allowed = ", ".join(str(d) for d in policy.terms_days)
        raise CaseActionError(f"Payment terms can be {allowed} days (the ERP's templates).")
    above = proposal.deposit_only or (
        proposal.credit_limit is not None and decision.credit_limit > proposal.credit_limit
    )
    if above and not (decision.reason and decision.reason.strip()):
        raise CaseActionError(
            "The limit is above the credit agent's proposal: say why you approve it."
        )
    return f"credit of {decision.credit_limit:,.2f} on {decision.terms_days} days approved"


# --- after the release: the customer in the ERP ---------------------------------------------


def terms_template(days: int) -> str:
    return "Due on receipt" if days == 0 else f"Net {days}"


async def create_customer(c: Ctx) -> None:
    """Released (the credit controller decided): queue the customer with exactly the
    approved terms (AR1.G1: never the agent's proposal) and post it right away."""
    if c.request is None:
        return
    app = need(c, "1.1.1.a", Application)
    decision = need(c, "1.2.2.a", CreditDecision)
    policy = policy_of(c.case, ArcPolicy)
    doc = await doc_of(c)
    credit = decision.decision == "approve_credit"
    home = app.country.strip().casefold() == policy.home_country.casefold()
    customer: dict[str, Any] = {
        "customer_name": app.legal_name,
        "customer_type": "Company",
        "customer_group": policy.customer_group,
        "territory": policy.home_country if home else "Rest Of The World",
        "tax_category": "Domestic" if home else "Export",
        "tax_id": app.tax_id,
        "payment_terms": terms_template(decision.terms_days or 0 if credit else 0),
        "email_id": app.billing_email,  # ERPNext makes it the primary contact
        "deposit_only": 0 if credit else 1,
        "credit_limits": (
            [{"company": doc.company_name, "credit_limit": str(cents(decision.credit_limit))}]
            if credit and decision.credit_limit is not None
            else []
        ),
    }
    task = await tasks.add_task(
        c.session, c.case,
        TaskCreate(kind=TaskKind.CREATE_CUSTOMER, reference=app.legal_name,
                   instructions={"doc": customer}),
        c.user.id,
    )  # fmt: skip
    # If the ERP refuses, the task stays proposed: a person posts it again from the case
    with contextlib.suppress(tasks.TaskRefusedError):
        await tasks.post_now(c.session, c.access, task, c.case, c.request)


# --- rules ---------------------------------------------------------------------------------


async def human_approval_rule(c: Ctx) -> str | None:
    """AR1.G1 No credit without human approval: the credit controller decided (1.2.2)."""
    if result(c, "1.2.1.b", CreditProposal) is None:
        return None
    if result(c, "1.2.2.a", CreditDecision) is None:
        return "No credit without the credit controller's decision (AR1.G1)."
    return None


async def documents_from_portal_rule(c: Ctx) -> str | None:
    """AR1.P3 Documents held in email: the client's documents are the ones they uploaded
    (through the portal, or by a person into the case), never an email attachment."""
    docs = result(c, "1.1.1.b", DocumentsUploaded)
    if docs is None:
        return None
    ids = [d for d in (docs.tax_form_id, *docs.registration_ids) if d]
    rows = list(await c.session.scalars(select(PodArtifact).where(PodArtifact.id.in_(ids))))
    if any(a.case_id != c.case.id or a.channel == ArtifactChannel.EMAIL for a in rows):
        return "The client's documents come through the portal into the case, not email (AR1.P3)."
    return None


# --- measures -------------------------------------------------------------------------------


async def setup_time(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AR1.M1 Account set-up time (days, median): opened -> client verified in the ERP."""
    if not cases:
        return None
    rows = await session.execute(
        select(PodPostingTask.case_id, PodPostingTask.verified_at).where(
            PodPostingTask.case_id.in_([c.id for c in cases]),
            PodPostingTask.kind == TaskKind.CREATE_CUSTOMER,
            PodPostingTask.status == TaskStatus.VERIFIED,
        )
    )
    opened = {c.id: c.created_at for c in cases}
    days = [(at - opened[cid]).total_seconds() / 86400 for cid, at in rows.all() if at]
    return Decimal(str(round(statistics.median(days), 1))) if days else None


async def data_errors(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AR1.M2 Data errors (%): applications the onboarding agent sent back with gaps."""
    applied = [c for c in cases if c.status != CaseStatus.CANCELLED or c.state.get("_gaps_flagged")]
    if not applied:
        return None
    flagged = sum(1 for c in applied if c.state.get("_gaps_flagged"))
    return cents(Decimal(flagged * 100) / len(applied))


# --- the daily limit review (AR1.R3, AR1.P2) --------------------------------------------------


async def newest_snapshot(session: AsyncSession, case: PodCase) -> PodSnapshot | None:
    """The newest snapshot of the case's source and entity (where the client lives now)."""
    source = await snapshots.source_of(session, case.snapshot_id)
    candidates = list(
        await session.scalars(
            select(PodSnapshot)
            .where(PodSnapshot.entity_id == case.entity_id)
            .order_by(PodSnapshot.created_at.desc())
            .limit(20)
        )
    )
    for snap in candidates:
        theirs = await snapshots.source_of(session, snap.id)
        same = source is None or (theirs is not None and theirs.id == source.id)
        if same and snapshots.document(snap).clients is not None:
            return snap
    return None


async def review_client(session: AsyncSession, case: PodCase) -> str | None:
    """One onboarded client: its limit against the newest books; a finding (review task)
    when it's nearly used or something is long overdue. Returns the suggestion."""
    created = case.state.get("_client")
    if not created:
        return None
    snapshot = await newest_snapshot(session, case)
    if snapshot is None:
        return None
    policy = ArcPolicy.model_validate(case.state.get("policy", {}).get("values", {}))
    found = agents.review(snapshots.document(snapshot), created, policy, utcnow().date())
    case.state = {**case.state, "_review": found.model_dump(mode="json")}
    if found.suggestion == "review":
        open_task = await session.scalar(
            select(PodReviewTask.id).where(
                PodReviewTask.case_id == case.id,
                PodReviewTask.subject == REVIEW,
                PodReviewTask.status == ReviewTaskStatus.OPEN,
            )
        )
        if open_task is None:
            session.add(
                PodReviewTask(
                    case_id=case.id, kind=ReviewTaskKind.OTHER, subject=REVIEW,
                    detail=(f"On {found.as_of}: {found.reason}. The credit controller reviews "
                            f"{created}'s limit ({found.credit_limit}) and terms (AR1.R3)."),
                    blocking=False, created_by=None,
                )
            )  # fmt: skip
    return found.suggestion


@jobs.daily(DAILY_JOB)
@jobs.handler(DAILY_JOB)
async def daily_review(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    onboarded = list(
        await session.scalars(
            select(PodCase).where(
                PodCase.workflow == KEY,
                PodCase.status.in_([CaseStatus.APPROVED, CaseStatus.COMPLETED]),
            )
        )
    )
    for case in onboarded:
        await review_client(session, case)
    await session.commit()


async def after_set_up(c: Ctx, step: StepSpec) -> str | None:
    """Remember which ERP client this case created, for the daily review."""
    created = need(c, "1.3.1.a", ClientCreated)
    c.case.state = {**c.case.state, "_client": created.erp_customer}
    return None
