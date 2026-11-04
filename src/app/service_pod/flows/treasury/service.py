"""Treasury rules: opening a forecast on a source (bank-verified cash, the AR promises to
review, the approved outflows), what blocks the Treasury Head and CFO sign-offs, and where a
case stands."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.common import selection
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    CommitmentStatus,
    PodApproval,
    PodCase,
    PodCommitment,
)
from src.app.service_pod.core.cases.service import Ctx, current_fingerprint
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.treasury import engine
from src.app.service_pod.flows.treasury.schemas import TreasurySelection

KEPT = ("scenarios",)


async def _receipts(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument
) -> list[dict[str, Any]]:
    """Approved, dated AR promises on this entity, checked against the source's balances."""
    rows = (
        await session.execute(
            select(PodCommitment, PodCase)
            .join(PodCase, PodCase.id == PodCommitment.case_id)
            .where(
                PodCase.entity_id == case.entity_id,
                PodCase.workflow == WorkflowKey.AR_COLLECTIONS,
                PodCase.status != CaseStatus.CANCELLED,
                PodCommitment.status == CommitmentStatus.APPROVED,
            )
            .order_by(PodCommitment.expected_date, PodCommitment.created_at)
        )
    ).all()
    invoices = {i.id: i for i in doc.invoices or []}
    customers = {c.id: c.name for c in doc.customers or []}
    promised: dict[str, Decimal] = {}
    for x, _ in rows:
        promised[x.invoice_id] = promised.get(x.invoice_id, Decimal(0)) + x.amount
    out = []
    for x, ar in rows:
        inv = invoices.get(x.invoice_id)
        rejected = None
        if x.expected_date is None:
            rejected = "No date: a tranche needs the customer's date."
        elif inv is None or inv.balance <= 0:
            rejected = (
                "The invoice is paid or not in this source: actual cash goes through bank "
                "verification, never a promise."
            )
        elif promised[x.invoice_id] > inv.balance:
            rejected = (
                f"The promises on {x.invoice_number} ({promised[x.invoice_id]}) exceed its "
                f"refreshed balance ({inv.balance}): the schedule is rejected."
            )
        elif x.expected_date <= doc.as_of:
            rejected = (
                f"Promised for {x.expected_date}, on or before the cash date: confirm it again."
            )
        out.append(
            {
                "id": str(x.id),
                "case_id": str(ar.id),
                "case_reference": ar.reference,
                "customer": customers.get(inv.customer_id, "") if inv else "",
                "invoice_id": x.invoice_id,
                "invoice_number": x.invoice_number,
                "amount": x.amount,
                "date": x.expected_date,
                "quote": x.quote,
                "probability": x.probability,
                "rejected": rejected,
                "review": None,
            }
        )
    return out


def recompute(case: PodCase) -> None:
    case.state = plain({**case.state, "results": engine.compute(case.state)})


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    selection.parse_selection(TreasurySelection, case.selection)
    cash, issues = engine.opening_cash(doc)
    receipts = await _receipts(session, case, doc)
    previous = case.state or {}
    # A review still holds while the tranche is the same promise (amount and date)
    reviews = {
        r["id"]: r["review"] for r in previous.get("receipts", []) if r.get("review") is not None
    }
    same = {(r["id"], str(r["amount"]), str(r["date"])) for r in previous.get("receipts", [])}
    for r in receipts:
        key = (r["id"], format(Decimal(str(r["amount"])).normalize(), "f"), str(r["date"]))
        if r["id"] in reviews and not r["rejected"] and key in same:
            r["review"] = reviews[r["id"]]
    case.state = plain(
        {
            "as_of": doc.as_of,
            "currency": doc.currency,
            "cash": cash,
            "issues": issues,
            "receipts": receipts,
            "outflows": [
                {
                    "id": o.id,
                    "date": o.date,
                    "amount": o.amount,
                    "category": o.category,
                    "approved": o.approved,
                    "approval_ref": o.approval_ref,
                }
                for o in doc.planned_outflows or []
            ],
            **{k: previous[k] for k in KEPT if k in previous},
        }
    )
    recompute(case)


def blocking(state: dict[str, Any]) -> list[str]:
    return [str(i["detail"]) for i in state.get("issues", []) if i.get("blocking")]


def unreviewed(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in state.get("receipts", []) if not r.get("rejected") and not r.get("review")]


def breach(state: dict[str, Any]) -> dict[str, Any] | None:
    base = (state.get("results") or {}).get("base") or {}
    return base if base.get("first_breach") else None


async def blockers(c: Ctx) -> list[str]:
    if c.case.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED):
        return []
    state = c.case.state
    problems = list(blocking(state))
    waiting = len(unreviewed(state))
    if waiting:
        problems.append(
            f"Review {waiting} imported receipt tranche{'s' if waiting > 1 else ''}: include it "
            "(with its probability) or leave it out."
        )
    base = breach(state)
    # A breach anywhere in the horizon (even one that recovers) needs an owned mitigation
    # (who, by when, outcome) before the sign-offs: the Treasury Head reviews it, the CFO
    # approves the plan with it
    if base and not c.children.actions:
        problems.append(
            f"The buffer is breached from {base['first_breach']} (largest shortfall "
            f"{state.get('currency', '')} {Decimal(str(base['max_shortfall'])):,.0f}): add an "
            "owned mitigation action (who, by when) before signing off."
        )
    return problems


async def _signed(session: AsyncSession, case: PodCase) -> set[str]:
    fingerprint = await current_fingerprint(session, case)
    rows = await session.scalars(
        select(PodApproval.capacity).where(
            PodApproval.case_id == case.id, PodApproval.content_hash == fingerprint
        )
    )
    return set(rows)


async def stage(session: AsyncSession, case: PodCase) -> str:
    """cash -> receipts -> forecast -> cfo, as the case page's steps."""
    if case.status == CaseStatus.APPROVED:
        return "cfo"
    if blocking(case.state):
        return "cash"
    if unreviewed(case.state):
        return "receipts"
    return "cfo" if "Treasury Head" in await _signed(session, case) else "forecast"


async def phase(session: AsyncSession, case: PodCase, blockers: list[str]) -> str:
    if blocking(case.state) or unreviewed(case.state):
        return "review"
    return "review" if blockers else "ready"


async def summary(session: AsyncSession, case: PodCase) -> str | None:
    base = (case.state.get("results") or {}).get("base")
    if not base:
        return None
    cur = case.state.get("currency", "")
    end = Decimal(str(base["ending_cash"]))
    tail = f" · buffer breached from {base['first_breach']}" if base.get("first_breach") else ""
    return f"13 weeks from {case.state.get('as_of')} · ending cash {cur} {end:,.0f}{tail}"


def event_amount(state: dict[str, Any], event_id: str) -> tuple[str, Decimal, date] | None:
    """(kind, nominal amount, date) of a base event a scenario may shift."""
    receipts, outflows = engine.events(state)
    for r in receipts:
        if r["id"] == event_id:
            return "receipt", r["amount"], date.fromisoformat(str(r["date"]))
    for o in outflows:
        if o["id"] == event_id:
            return "outflow", o["amount"], date.fromisoformat(str(o["date"]))
    return None
