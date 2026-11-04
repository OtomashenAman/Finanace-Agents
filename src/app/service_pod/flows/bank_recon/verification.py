"""Verifying the manual Receive Payment against a fresh export (TDD section 7)."""

from src.app.service_pod.common import reading
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.tasks.models import PodPostingTask
from src.app.service_pod.flows.bank_recon.service import receipt_of


def verify_posting(
    task: PodPostingTask, case: PodCase, original: SnapshotDocument, fresh: SnapshotDocument
) -> list[str]:
    """The fresh books must show exactly the payment that was approved (TDD section 7)."""
    receipt = receipt_of(case)
    allocation = case.state.get("allocation") or {}
    ref = str(receipt["reference"]).lower()
    matches = [p for p in fresh.payments or [] if p.reference.lower() == ref]
    if len(matches) != 1:
        return [
            f"Expected one payment with reference {receipt['reference']}, found {len(matches)}."
        ]
    pay = matches[0]
    problems = []
    if pay.id != task.external_txn_id and pay.reference != task.external_txn_id:
        problems.append(f"The payment's ID is {pay.id}, not the recorded {task.external_txn_id}.")
    if pay.date.isoformat() != receipt["date"]:
        problems.append(f"Payment date {pay.date} differs from the bank date {receipt['date']}.")
    if pay.customer_id != case.state["customer"]["id"]:
        problems.append("The payment is on another customer.")
    if pay.amount != reading.dec(receipt["amount"]) or pay.currency != receipt["currency"]:
        problems.append("The payment's amount or currency differs from the receipt.")
    wanted = {
        str(line["invoice_id"]): reading.dec(line["amount"]) for line in allocation.get("lines", [])
    }
    applied = {a.invoice_id: a.amount for a in pay.allocations}
    if applied != wanted:
        problems.append("The payment isn't applied to the invoices exactly as approved.")
    before = {i.id: i.balance for i in original.invoices or []}
    after = {i.id: i.balance for i in fresh.invoices or []}
    for invoice_id, amount in wanted.items():
        if invoice_id in before and after.get(invoice_id) != before[invoice_id] - amount:
            problems.append(
                f"Invoice {invoice_id}'s remaining balance isn't {before[invoice_id] - amount}."
            )
    return problems
