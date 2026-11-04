"""AR Collections: the case selection and the AI's reading of a reply."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.app.service_pod.common.worklists import CaseRef, InvoiceRow
from src.app.service_pod.core.snapshots.schemas import SnapshotSummary


class ArSelection(BaseModel):
    customer_id: str = Field(min_length=1)
    invoice_ids: list[str] = Field(min_length=1, max_length=50)


class ArTranche(BaseModel):
    invoice_number: str = Field(description="One of the invoice numbers listed")
    amount: str = Field(
        description="Amount promised, digits only, e.g. 6000.00; empty if the customer states none"
    )
    date: str | None = Field(
        description="YYYY-MM-DD only if the customer names a calendar date, else null "
        "('now', 'initially', 'soon' are not dates)"
    )
    quote: str = Field(description="The customer's exact words for this payment")
    inferred: bool = Field(
        description="True if the invoice or amount isn't written in the quote (e.g. 'both')"
    )
    confidence: float = Field(description="0 to 1")


class ArDispute(BaseModel):
    invoice_number: str
    amount: str | None = Field(description="Disputed amount if stated, digits only")
    reason: str
    quote: str = Field(description="The customer's exact words")


class ArDocumentRequest(BaseModel):
    kind: str = Field(description="timesheet, invoice_copy, msa or other")
    invoice_numbers: list[str] = Field(description="Invoices it concerns (may be empty)")
    quote: str = Field(description="The customer's exact words")


class ArReplyRead(BaseModel):
    intent: str = Field(description="One short phrase, e.g. 'partial promise + timesheets'")
    tranches: list[ArTranche]
    disputes: list[ArDispute]
    document_requests: list[ArDocumentRequest]
    unclear: list[str] = Field(description="Anything ambiguous or missing, in plain words")


# --- worklist responses ----------------------------------------------------------


class AgingBucket(BaseModel):
    label: str
    amount: Decimal
    count: int


class PortfolioCustomer(BaseModel):
    customer_id: str
    name: str
    email: str | None
    overdue: Decimal
    max_days_overdue: int
    invoices: list[InvoiceRow]  # overdue with an open balance
    open_case: CaseRef | None
    next_action: str


class PromiseRow(BaseModel):
    """An approved promise being watched: when it's due and whether cash came in."""

    case_id: uuid.UUID
    case_reference: str
    customer: str
    invoice_number: str
    amount: Decimal
    expected_date: date
    days_until: int  # negative: overdue by that many days
    state: Literal["upcoming", "due", "overdue", "received"]
    received_by: str | None  # the evidence: a verified bank posting or a newer source


class ArPortfolio(BaseModel):
    snapshot: SnapshotSummary | None
    currency: str | None
    ar_balance: Decimal
    overdue_over_30: Decimal
    approved_promises: Decimal
    open_exceptions: int
    aging: list[AgingBucket]
    customers: list[PortfolioCustomer]
    promises: list[PromiseRow]
