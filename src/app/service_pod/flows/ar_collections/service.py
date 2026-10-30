"""AR Collections rules: what a case may be opened on, what blocks approval, and the
messages it sends (verified invoice figures + wording)."""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMProvider
from src.app.service_pod.common import drafting, reading, selection
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    CommitmentStatus,
    PodCase,
)
from src.app.service_pod.core.cases.service import Ctx
from src.app.service_pod.core.hooks import Composed
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.flows.ar_collections.schemas import ArSelection

PURPOSES = {
    "payment_schedule_request": "Ask for amounts and payment dates",
    "follow_up": "Follow-up reply",
}


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    sel = selection.parse_selection(ArSelection, case.selection)
    customer = next((c for c in doc.customers or [] if c.id == sel.customer_id), None)
    if customer is None:
        raise CaseSelectionError("That customer isn't in the source.")
    by_id = {i.id: i for i in doc.invoices or []}
    if len(set(sel.invoice_ids)) != len(sel.invoice_ids):
        raise CaseSelectionError("An invoice is selected twice.")
    rows = []
    for invoice_id in sel.invoice_ids:
        inv = by_id.get(invoice_id)
        if inv is None or inv.customer_id != customer.id:
            raise CaseSelectionError(f"Invoice {invoice_id} isn't one of {customer.name}'s.")
        # Any invoice past its due date with an open balance can be collected (TDD); after a
        # refresh an invoice may since have been paid, which the case then shows
        if not refresh and (inv.balance <= 0 or inv.due_date >= doc.as_of):
            raise CaseSelectionError(f"{inv.number} isn't overdue with an open balance.")
        rows.append(
            {
                "id": inv.id,
                "number": inv.number,
                "due_date": inv.due_date,
                "original_amount": inv.original_amount,
                "balance": inv.balance,
                "days_overdue": max(0, (doc.as_of - inv.due_date).days),
            }
        )
    case.state = plain(
        {
            **case.state,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "contact_name": customer.contact_name,
            },
            "currency": doc.currency,
            "as_of": doc.as_of,
            "invoices": rows,
            "total_open": sum((by_id[i].balance for i in sel.invoice_ids), Decimal(0)),
        }
    )


def invoices_of(case: PodCase) -> dict[str, dict[str, object]]:
    return {str(r["number"]): r for r in case.state.get("invoices", [])}


async def blockers(c: Ctx) -> list[str]:
    if c.case.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED):
        return []
    problems = []
    undecided = [x for x in c.children.commitments if x.status == CommitmentStatus.PROPOSED]
    if undecided:
        problems.append(f"Decide the {len(undecided)} proposed commitment(s) first.")
    invoices = invoices_of(c.case)
    promised: dict[str, Decimal] = defaultdict(Decimal)
    for x in c.children.commitments:
        if x.status != CommitmentStatus.REJECTED:
            promised[x.invoice_number] += x.amount
    for number, total in promised.items():
        row = invoices.get(number)
        if row is not None and total > reading.dec(row["balance"]):
            problems.append(f"Commitments on {number} exceed its current open balance.")
    newer = await system.newer_snapshot(c.session, c.case)
    if newer is not None:
        fresh = {i.number: i for i in snapshots.document(newer).invoices or []}
        changed = [
            n
            for n, row in invoices.items()
            if n not in fresh
            or fresh[n].balance != reading.dec(row["balance"])
            or fresh[n].due_date.isoformat() != row["due_date"]
        ]
        if changed:
            problems.append(
                f"A newer source (as of {newer.as_of.isoformat()}) changes "
                f"{', '.join(changed)}: refresh the case's source first."
            )
    return problems


async def facts(session: AsyncSession, case: PodCase, purpose: str) -> str | None:
    currency = str(case.state["currency"])
    rows = [("Invoice", "Due date", "Open balance")]
    rows += [
        (str(r["number"]), str(r["due_date"]), reading.money(reading.dec(r["balance"]), currency))
        for r in case.state.get("invoices", [])
    ]
    total = reading.money(reading.dec(case.state["total_open"]), currency)
    return f"{drafting.table(rows)}\nTotal open: {total}"


async def compose(session: AsyncSession, case: PodCase, purpose: str, llm: LLMProvider) -> Composed:
    customer = case.state["customer"]
    numbers = " / ".join(invoices_of(case))
    fact_block = await facts(session, case, purpose)
    assert fact_block is not None  # noqa: S101
    schedule = purpose == "payment_schedule_request"
    return await drafting.compose(
        llm,
        to_email=customer.get("email"),
        to_name=customer.get("contact_name") or customer.get("name"),
        subject=f"Confirm payment schedule for {numbers}" if schedule else f"Re: {numbers}",
        fact_block=fact_block,
        ask=(
            "Ask the customer to confirm, for each invoice listed, the amount and the date "
            "they will pay, and to say if they need signed timesheets or invoice copies."
            if schedule
            else "Follow up on the invoices listed, thanking them for their reply and asking "
            "for whatever is still missing."
        ),
        template_opening=(
            f"Dear {customer.get('contact_name') or customer.get('name')},\n\n"
            "Our records show the invoices below as outstanding. Please confirm the payment "
            "amount and expected date for each. If you need signed timesheets or invoice "
            "copies, please tell us."
        ),
        template_closing="Thank you,",
    )
