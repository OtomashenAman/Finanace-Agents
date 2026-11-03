"""The purchase request's own rules: opening a case, what people's decisions do, the
requirement's business rules and guardrails, its measures and the buyer's actions."""

from __future__ import annotations

import statistics
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.common.clock import utcnow
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.common import need, policy_values, result, snapshot_of
from src.app.finance_pod.flows.ap_purchase_request.policy import PrqPolicy
from src.app.finance_pod.flows.ap_purchase_request.results import (
    AcknowledgePayload,
    BudgetCheck,
    BudgetDecision,
    Comparison,
    GrantCheck,
    QuoteUpload,
    RecordQuotePayload,
    Routing,
    VendorChoice,
)
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseSelectionError
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.messaging.models import ArtifactKind, PodArtifact
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.steps import service as steps
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.spec import StepSpec, StepStatus
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import ActionSpec, Ctx

KEY = WorkflowKey.AP_PURCHASE_REQUEST


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    """A request may start from one already raised in the ERP (its quotations count)."""
    request_id = case.selection.get("erp_request_id")
    if request_id and request_id not in {r.id for r in doc.purchase_requests or []}:
        raise CaseSelectionError(f"Purchase request {request_id} isn't in this snapshot.")
    unknown = set(case.selection) - {"erp_request_id"}
    if unknown:
        raise CaseSelectionError(f"Unknown selection: {', '.join(sorted(unknown))}.")
    if not refresh:
        version, values = await policy_values(session, KEY.value, PrqPolicy)
        case.state = {
            **case.state,
            "policy": {"version": version, "values": values.model_dump(mode="json")},
        }


# --- what people's decisions do ------------------------------------------------------------


async def after_need(c: Ctx, step: StepSpec) -> str | None:
    """1.1.1: the quote must be a document of this case."""
    quote = need(c, "1.1.1.b", QuoteUpload)
    if quote.document_id is not None:
        doc = await c.session.get(PodArtifact, quote.document_id)
        if doc is None or doc.case_id != c.case.id or doc.kind != ArtifactKind.QUOTE:
            raise CaseActionError("Attach the quote to this request first (a quote document).")
    return None


async def after_budget_decision(c: Ctx, step: StepSpec) -> str | None:
    decision = need(c, "1.2.2.b", BudgetDecision)
    if decision.decision == "approve":
        # The budget agent's findings can't be waved through silently: a grant that can't
        # take the charge must be queried or rejected; an over-budget approval says why
        grant = result(c, "1.2.1.b", GrantCheck)
        if grant is not None and grant.applies and not grant.allowed:
            raise CaseActionError(
                f"The grant can't take this charge ({'; '.join(grant.problems)}): query the "
                "requester to recode it, or reject."
            )
        budget = result(c, "1.2.1.a", BudgetCheck)
        if budget is not None and not budget.within_budget:
            if not (decision.comment and decision.comment.strip()):
                flagged = "; ".join(
                    f"{ln.against.replace('_', ' ')} {ln.target_id} / {ln.account_id}: "
                    + ("no budget set" if ln.budget is None else f"{ln.remaining_after} left")
                    for ln in budget.lines
                    if ln.over
                )
                raise CaseActionError(
                    f"The budget agent flagged this request ({flagged}): say why you approve it."
                )
            return f"approved over budget: {decision.comment}"
    if decision.decision == "reject":
        c.case.status = CaseStatus.CANCELLED
        return f"rejected by the budget owner: {decision.comment}"
    if decision.decision == "query":
        await steps.send_back(c, "1.1.1", f"budget owner's query: {decision.comment}")
        return f"sent back to the requester: {decision.comment}"
    return None


async def after_choice(c: Ctx, step: StepSpec) -> str | None:
    """1.3.2: an active vendor from the master, the quote's reason, or a new vendor's
    onboarding (AP1.R4: if new, request set-up; if existing, go to PO)."""
    from src.app.service_pod.core.cases.service import open_case

    choice = need(c, "1.3.2.b", VendorChoice)
    comparison = result(c, "1.3.1.c", Comparison)
    snapshot = await snapshot_of(c)
    from src.app.service_pod.core.snapshots.service import document

    doc = document(snapshot)
    vendors = {v.id: v for v in doc.vendors or []}
    quotes = {q.reference: q for q in (comparison.quotes if comparison else [])}
    if choice.quote_reference and choice.quote_reference not in quotes:
        raise CaseActionError(f"{choice.quote_reference} isn't one of the compared quotes.")
    not_cheapest = (
        comparison and comparison.cheapest and choice.quote_reference != comparison.cheapest
    )
    if not_cheapest and not (choice.reason and choice.reason.strip()):
        raise CaseActionError("Say why you didn't choose the cheapest quote.")
    if choice.vendor_id:
        vendor = vendors.get(choice.vendor_id)
        if vendor is None:
            raise CaseActionError(f"{choice.vendor_id} isn't in the vendor master.")
        if vendor.status != "Active":
            raise CaseActionError(f"{vendor.name} is {vendor.status}: choose another vendor.")
        return f"vendor {vendor.name}"
    assert choice.new_vendor_name is not None  # noqa: S101 - the model requires one
    taken = {v.name.casefold() for v in vendors.values()}
    if choice.new_vendor_name.casefold() in taken:
        raise CaseActionError(f"{choice.new_vendor_name} is already a vendor: choose it.")
    if c.case.state.get("vendor_case"):
        return f"new vendor {choice.new_vendor_name} (onboarding already open)"
    onboarding = await open_case(
        c.session, c.access, WorkflowKey.AP_VENDOR_ONBOARDING, snapshot,
        f"Onboard {choice.new_vendor_name}",
        {"vendor_name": choice.new_vendor_name, "contact_email": str(choice.new_vendor_email),
         "for_case": str(c.case.id)},
        c.request, opened_from=c.case,
    )  # fmt: skip
    c.case.state = {**c.case.state, "vendor_case": str(onboarding.id)}
    return f"new vendor {choice.new_vendor_name}: onboarding {onboarding.reference} opened"


# --- the requirement's rules ---------------------------------------------------------------


async def quotes_rule(c: Ctx) -> str | None:
    """AP1.R1 Quotes required above purchasing threshold."""
    routing = result(c, "1.2.1.c", Routing)
    comparison = result(c, "1.3.1.c", Comparison)
    if routing is None or not routing.quotes_required or comparison is None:
        return None
    if len(comparison.quotes) < comparison.required:
        return f"{comparison.required} quotes are required above the threshold (AP1.R1)."
    return None


async def approved_request_rule(c: Ctx) -> str | None:
    """AP1.G1 No PO without approved request."""
    decision = result(c, "1.2.2.b", BudgetDecision)
    if steps.status_of(c.children.steps, "1.6.1") != StepStatus.PENDING and (
        decision is None or decision.decision != "approve"
    ):
        return "No PO without an approved request: the budget owner hasn't approved it (AP1.G1)."
    return None


async def new_vendor_rule(c: Ctx) -> str | None:
    """AP1.R4 A new vendor is set up (onboarding complete) before the PO."""
    link = c.case.state.get("vendor_case")
    if not link:
        return None
    onboarding = await c.session.get(PodCase, uuid.UUID(link))
    if onboarding is None or onboarding.status != CaseStatus.COMPLETED:
        ref = onboarding.reference if onboarding else "its onboarding"
        return f"The new vendor isn't set up yet: {ref} must complete first (AP1.R4)."
    return None


# --- measures -------------------------------------------------------------------------------


async def cycle_time(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP1.M1 Request-to-PO cycle time (hours, median): opened -> PO sent."""
    if not cases:
        return None
    rows = await session.execute(
        select(PodCaseStep.case_id, PodCaseStep.done_at).where(
            PodCaseStep.case_id.in_([c.id for c in cases]),
            PodCaseStep.l5_code == "1.6.1.c",
            PodCaseStep.status == StepStatus.DONE,
        )
    )
    opened = {c.id: c.created_at for c in cases}
    hours = [(done - opened[cid]).total_seconds() / 3600 for cid, done in rows.all() if done]
    return Decimal(str(round(statistics.median(hours), 1))) if hours else None


async def rework_rate(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP1.M2 Requests needing rework (% sent back to the requester at least once)."""
    if not cases:
        return None
    reworked = await session.scalar(
        select(func.count(func.distinct(AuditEvent.details["case_id"].astext))).where(
            AuditEvent.event_type == "finance.step_sent_back",
            AuditEvent.details["step"].astext == "1.1.1",
            AuditEvent.details["case_id"].astext.in_([str(c.id) for c in cases]),
        )
    )
    return Decimal(str(round(100 * (reworked or 0) / len(cases), 1)))


# --- the buyer's actions ---------------------------------------------------------------------


def _buyer(c: Ctx) -> str | None:
    if not c.access.holds(Cap.BUYER.value, c.case.entity_id):
        return "Only a buyer can do this."
    return None


def _guard_quote(c: Ctx) -> str | None:
    if c.case.status != CaseStatus.DRAFT:
        return "Quotes are recorded while the request is open."
    if steps.status_of(c.children.steps, "1.3.2") != StepStatus.PENDING:
        return "The vendor is already chosen."
    return _buyer(c)


async def _record_quote(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, RecordQuotePayload)  # noqa: S101
    document = await c.session.get(PodArtifact, p.document_id)
    if document is None or document.case_id != c.case.id or document.kind != ArtifactKind.QUOTE:
        raise CaseActionError("Attach the quote document to this request first.")
    quotes: list[dict[str, Any]] = list(c.case.state.get("quotes", []))
    if any(q["reference"] == p.reference for q in quotes):
        raise CaseActionError(f"Quote {p.reference} is already recorded.")
    quotes.append(
        {"vendor_id": p.vendor_id, "vendor_name": p.vendor_name, "reference": p.reference,
         "total": str(p.total), "lead_time_days": p.lead_time_days,
         "valid_till": p.valid_till.isoformat() if p.valid_till else None, "terms": p.terms,
         "document_id": str(p.document_id),
         "rates": {k: str(v) for k, v in p.rates.items()}}
    )  # fmt: skip
    c.case.state = {**c.case.state, "quotes": quotes}
    return f"Recorded quote {p.reference} from {p.vendor_name} ({p.total})", True


def _guard_acknowledge(c: Ctx) -> str | None:
    if c.case.status != CaseStatus.APPROVED:
        return "The acknowledgement is logged once the PO is out."
    return _buyer(c)


async def _acknowledge(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, AcknowledgePayload)  # noqa: S101
    c.case.state = {
        **c.case.state,
        "_po_acknowledgement": {"how": p.how, "note": p.note, "logged_by": c.user.full_name,
                                "logged_at": utcnow().isoformat()},
    }  # fmt: skip
    # An execution detail of the released request: what was approved doesn't change
    return f"Logged the vendor's acknowledgement ({p.how})", False


def actions() -> dict[str, ActionSpec]:
    from src.app.service_pod.core.cases.service import ActionSpec

    return {
        "record_quote": ActionSpec(RecordQuotePayload, _guard_quote, _record_quote),
        "log_acknowledgement": ActionSpec(AcknowledgePayload, _guard_acknowledge, _acknowledge),
    }
