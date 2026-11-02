"""Bank-to-Invoice: the case selection, the allocation actions and the AI's reading of a reply."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from src.app.service_pod.common.worklists import CaseRef, InvoiceRow
from src.app.service_pod.core.snapshots.schemas import SnapshotSummary


class BankSelection(BaseModel):
    receipt_reference: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    # When the bank's payer name differs from the customer (e.g. a parent company pays):
    # the evidence that this customer is the payer
    payer_confirmation: str | None = Field(default=None, max_length=1000)


class AllocationLine(BaseModel):
    invoice_id: str
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class SetAllocationPayload(BaseModel):
    """Recorded by hand from a reply (when the AI couldn't, or got it wrong)."""

    lines: list[AllocationLine] = Field(min_length=1, max_length=50)
    source_message_id: str
    quote: str = Field(min_length=3, max_length=4000)


class BankAllocationRead(BaseModel):
    invoice_number: str = Field(description="One of the open invoice numbers listed")
    amount: str = Field(
        description="Amount to apply, digits only, e.g. 6000.00; empty if the customer states none"
    )
    quote: str = Field(description="The customer's exact words for this line")
    confidence: float = Field(description="0 to 1")


class BankDocumentRequest(BaseModel):
    kind: str = Field(description="timesheet, invoice_copy, msa or other")
    invoice_numbers: list[str]
    quote: str


class BankReplyRead(BaseModel):
    allocations: list[BankAllocationRead]
    document_requests: list[BankDocumentRequest]
    unclear: list[str] = Field(description="Anything ambiguous or missing, in plain words")


# --- worklist responses ----------------------------------------------------------


class ReceiptRow(BaseModel):
    reference: str
    payer: str
    date: date
    amount: Decimal
    currency: str
    cleared: bool
    matched_customer_id: str | None
    matched_customer: str | None
    open_invoices: list[InvoiceRow]
    possible_duplicate: bool
    open_case: CaseRef | None


class BankWorklist(BaseModel):
    snapshot: SnapshotSummary | None
    unmatched_total: Decimal
    receipts: int
    possible_duplicates: int
    pending_admin: int
    rows: list[ReceiptRow]
