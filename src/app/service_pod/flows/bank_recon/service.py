"""Bank-to-Invoice rules: a cleared receipt and its verified payer, the customer's allocation
(which must settle the receipt exactly), what blocks approval, and the messages."""

from collections import Counter
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMProvider
from src.app.service_pod.common import drafting, matching, reading, selection
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases import progress, system
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.cases.service import (
    Ctx,
)
from src.app.service_pod.core.hooks import Composed
from src.app.service_pod.core.messaging.models import PodMessage
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.bank_recon.schemas import BankSelection

PURPOSES = {
    "allocation_request": "Ask which invoices the payment covers",
    "acknowledgement": "Confirm how the payment was applied",
}


def receipt_of(case: PodCase) -> dict[str, Any]:
    return case.state["receipt"]  # type: ignore[no-any-return]


def open_invoices_of(case: PodCase) -> dict[str, dict[str, Any]]:
    return {str(r["id"]): r for r in case.state.get("open_invoices", [])}


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    sel = selection.parse_selection(BankSelection, case.selection)
    ref = sel.receipt_reference.lower()
    receipt = next((r for r in doc.bank_receipts or [] if r.reference.lower() == ref), None)
    if receipt is None:
        raise CaseSelectionError("That receipt isn't in the source's bank receipts.")
    customer = next((c for c in doc.customers or [] if c.id == sel.customer_id), None)
    if customer is None:
        raise CaseSelectionError("That customer isn't in the source.")
    if not refresh:
        if not receipt.cleared:
            raise CaseSelectionError("Only cleared bank receipts can be applied.")
        if receipt.currency != doc.currency:
            raise CaseSelectionError(
                f"The receipt is in {receipt.currency}, the books in {doc.currency}."
            )
        if any(p.reference.lower() == ref for p in doc.payments or []):
            raise CaseSelectionError("A payment with this reference is already recorded.")
        names_match = matching.customer_key(receipt.payer) == matching.customer_key(customer.name)
        if not names_match and len((sel.payer_confirmation or "").strip()) < 10:
            raise CaseSelectionError(
                f"The payer ({receipt.payer}) isn't {customer.name}: say how you verified "
                "that this customer paid (payer_confirmation)."
            )
        other = await session.scalar(
            select(PodCase.id).where(
                PodCase.workflow == WorkflowKey.BANK_RECON,
                PodCase.entity_id == case.entity_id,
                PodCase.selection["receipt_reference"].astext == sel.receipt_reference,
                PodCase.status != CaseStatus.CANCELLED,
            )
        )
        if other is not None:
            raise CaseSelectionError("Another open case already handles this receipt.")
    open_invoices = [
        {"id": i.id, "number": i.number, "due_date": i.due_date, "balance": i.balance}
        for i in doc.invoices or []
        if i.customer_id == customer.id and i.balance > 0
    ]
    case.state = plain(
        {
            **case.state,
            "receipt": receipt,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "contact_name": customer.contact_name,
            },
            "currency": doc.currency,
            "open_invoices": open_invoices,
        }
    )


def allocation_problems(case: PodCase) -> list[str]:
    allocation = case.state.get("allocation")
    if not allocation:
        return ["No customer allocation yet: ask the customer which invoices the payment covers."]
    receipt_amount = reading.dec(receipt_of(case)["amount"])
    invoices = open_invoices_of(case)
    lines = allocation.get("lines", [])
    problems = []
    if not lines:
        problems.append("The allocation has no lines.")
    counts = Counter(str(line["invoice_id"]) for line in lines)
    if any(n > 1 for n in counts.values()):
        problems.append("An invoice appears twice in the allocation.")
    for line in lines:
        inv = invoices.get(str(line["invoice_id"]))
        amount = reading.dec(line["amount"])
        if inv is None:
            problems.append(f"{line.get('invoice_number')} isn't an open invoice of this customer.")
        elif amount <= 0 or amount > reading.dec(inv["balance"]):
            problems.append(f"{inv['number']}: {amount} is outside its open balance.")
    total = sum((reading.dec(line["amount"]) for line in lines), Decimal(0))
    if total != receipt_amount:
        problems.append(f"The lines total {total}, the receipt is {receipt_amount}.")
    if not allocation.get("source_message_id"):
        problems.append("The allocation must come from the customer's reply.")
    return problems


def store_allocation(
    case: PodCase, lines: list[tuple[str, Decimal]], reply: PodMessage, quote: str, by: str
) -> None:
    invoices = open_invoices_of(case)
    case.state = plain(
        {
            **case.state,
            "allocation": {
                "lines": [
                    {"invoice_id": i, "invoice_number": invoices[i]["number"], "amount": a}
                    for i, a in lines
                ],
                "source_message_id": str(reply.id),
                "quote": quote,
                "by": by,
            },
        }
    )


async def blockers(c: Ctx) -> list[str]:
    if c.case.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED):
        return []
    problems = allocation_problems(c.case)
    newer = await system.newer_snapshot(c.session, c.case)
    if newer is not None:
        doc = snapshots.document(newer)
        ref = receipt_of(c.case)["reference"].lower()
        if any(p.reference.lower() == ref for p in doc.payments or []):
            problems.append(
                f"A newer source (as of {newer.as_of.isoformat()}) already records this payment."
            )
        fresh = {i.id: i.balance for i in doc.invoices or []}
        changed = [
            str(r["number"])
            for i, r in open_invoices_of(c.case).items()
            if fresh.get(i) != reading.dec(r["balance"])
        ]
        if changed:
            problems.append(
                f"A newer source changes {', '.join(changed)}: refresh the case's source first."
            )
    return problems


async def _verified(session: AsyncSession, case: PodCase) -> bool:
    return (
        await session.scalar(
            select(PodPostingTask.id).where(
                PodPostingTask.case_id == case.id,
                PodPostingTask.kind == TaskKind.RECEIVE_PAYMENT,
                PodPostingTask.status == TaskStatus.VERIFIED,
            )
        )
    ) is not None


async def draft_blocker(session: AsyncSession, case: PodCase, purpose: str) -> str | None:
    if purpose == "acknowledgement" and not await _verified(session, case):
        return "Confirm to the customer only after the posting is verified in QuickBooks."
    return None


async def facts(session: AsyncSession, case: PodCase, purpose: str) -> str | None:
    receipt = receipt_of(case)
    currency = str(receipt["currency"])
    amount = reading.money(reading.dec(receipt["amount"]), currency)
    if purpose == "acknowledgement":
        lines = case.state["allocation"]["lines"]
        applied = [("Invoice", "Applied")] + [
            (str(line["invoice_number"]), reading.money(reading.dec(line["amount"]), currency))
            for line in lines
        ]
        return f"Payment {receipt['reference']} of {amount}, applied as:\n{drafting.table(applied)}"
    rows = [("Invoice", "Due date", "Open balance")] + [
        (str(r["number"]), str(r["due_date"]), reading.money(reading.dec(r["balance"]), currency))
        for r in case.state.get("open_invoices", [])
    ]
    return (
        f"Payment received: {receipt['reference']}, {amount} on {receipt['date']}\n"
        f"Your open invoices:\n{drafting.table(rows)}"
    )


async def compose(session: AsyncSession, case: PodCase, purpose: str, llm: LLMProvider) -> Composed:
    customer = case.state["customer"]
    receipt = receipt_of(case)
    fact_block = await facts(session, case, purpose)
    assert fact_block is not None  # noqa: S101
    ack = purpose == "acknowledgement"
    name = customer.get("contact_name") or customer.get("name")
    return await drafting.compose(
        llm,
        to_email=customer.get("email"),
        to_name=name,
        subject=(
            f"Payment {receipt['reference']} applied"
            if ack
            else f"Please allocate payment {receipt['reference']}"
        ),
        fact_block=fact_block,
        ask=(
            "Confirm to the customer that their payment was applied to the invoices listed."
            if ack
            else "Thank the customer for the payment and ask which invoices and amounts it "
            "covers; offer invoice copies if they need them."
        ),
        template_opening=(
            f"Dear {name},\n\n"
            + (
                "Your payment has been applied as follows."
                if ack
                else "Thank you for your payment. Please tell us which invoices, and how much "
                "of each, it covers. We can send invoice copies if needed."
            )
        ),
        template_closing="Thank you,",
    )


async def stage(session: AsyncSession, case: PodCase) -> str:
    """request -> allocation -> posting, as the case page's steps."""
    p = await progress.progress(session, case, "allocation_request")
    if not p.request_sent:
        return "request"
    if not p.replied or not case.state.get("allocation") or p.open_tasks:
        return "allocation"
    return "posting"


async def summary(session: AsyncSession, case: PodCase) -> str | None:
    """e.g. "WIRE-2901 USD 9,000.00 → INV-101 6,000.00, INV-102 3,000.00 · posting verified"."""
    receipt = receipt_of(case)
    currency = str(receipt.get("currency", ""))
    head = f"{receipt['reference']} {reading.money(reading.dec(receipt['amount']), currency)}"
    lines = (case.state.get("allocation") or {}).get("lines", [])
    if not lines:
        return f"{head} · waiting for the customer's allocation"
    applied = ", ".join(
        f"{line['invoice_number']} {reading.dec(line['amount']):,.2f}" for line in lines
    )
    status = await session.scalar(
        select(PodPostingTask.status).where(
            PodPostingTask.case_id == case.id, PodPostingTask.kind == TaskKind.RECEIVE_PAYMENT
        )
    )
    posting = f"posting {status.value.replace('_', ' ')}" if status else "posting not queued"
    return f"{head} → {applied} · {posting}"
