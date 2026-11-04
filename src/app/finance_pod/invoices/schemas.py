import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.app.finance_pod.invoices.models import (
    ExceptionDecision,
    ExceptionStatus,
    InvoiceStatus,
    ReceiptRequestStatus,
)


class InvoiceLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    po_line: int | None = Field(default=None, ge=1)


class InvoiceIn(BaseModel):
    """The invoice's data as AP confirms it (3.1: what the capture agent read, corrected)."""

    vendor_code: str | None = Field(default=None, max_length=40)
    vendor_invoice_number: str | None = Field(default=None, max_length=80)
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    tax_code: str | None = Field(default=None, max_length=40)
    tax_total: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    total: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    po_reference: str | None = Field(default=None, max_length=40)
    lines: list[InvoiceLineIn] = Field(default_factory=list, max_length=200)


class InvoiceUpdate(InvoiceIn):
    expected_version: int


class VersionIn(BaseModel):
    expected_version: int


class NoteIn(VersionIn):
    note: str = Field(min_length=3, max_length=2000)


class Amendment(BaseModel):
    po_line: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class DecisionIn(BaseModel):
    """The buyer's decision on a variance (3.5.2.a)."""

    decision: ExceptionDecision
    note: str = Field(min_length=3, max_length=2000)
    amendments: list[Amendment] = Field(default_factory=list, max_length=200)
    credit_expected: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    query_subject: str | None = Field(default=None, max_length=300)
    query_body: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def _amendments(self) -> "DecisionIn":
        if self.decision == ExceptionDecision.AMEND_PO and not self.amendments:
            raise ValueError("amending the PO needs the new line values")
        return self


class DeleteIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class CreditNoteIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reference: str = Field(min_length=1, max_length=80)


class ReceiptLineIn(BaseModel):
    po_line: int = Field(ge=1)
    quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class ReceiptIn(BaseModel):
    received_on: date
    lines: list[ReceiptLineIn] = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=2000)


class InvoiceLineOut(BaseModel):
    position: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    po_line: int | None


class ExceptionOut(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_reference: str
    vendor_name: str | None
    po_reference: str | None
    status: ExceptionStatus
    kinds: list[str]
    issues: list[dict[str, Any]]
    vendor_query_subject: str | None
    vendor_query_body: str | None
    decision: ExceptionDecision | None
    decided_by_name: str | None
    decided_at: datetime | None
    note: str | None
    credit_expected: Decimal | None
    credit_received: Decimal | None
    credit_note_ref: str | None
    created_at: datetime
    resolved_at: datetime | None
    age_days: float
    total: Decimal | None
    currency: str


class ReceiptOut(BaseModel):
    id: uuid.UUID
    received_on: date
    receiver_email: str | None
    via: str
    notes: str | None
    lines: list[dict[str, Any]]
    created_at: datetime


class ReceiptRequestOut(BaseModel):
    id: uuid.UUID
    po_id: uuid.UUID
    receiver_email: str
    receiver_name: str | None
    status: ReceiptRequestStatus
    nudges: int
    last_nudged_at: datetime | None
    confirmed_at: datetime | None
    expires_at: datetime | None
    link: str | None  # only right after it was issued


class InvoiceSummary(BaseModel):
    id: uuid.UUID
    reference: str
    status: InvoiceStatus
    vendor_code: str | None
    vendor_name: str | None
    vendor_invoice_number: str | None
    invoice_date: date | None
    total: Decimal | None
    currency: str
    po_reference: str | None
    first_pass_matched: bool | None
    created_at: datetime


class InvoiceOut(InvoiceSummary):
    version: int
    due_date: date | None
    tax_code: str | None
    tax_total: Decimal
    po_id: uuid.UUID | None
    filename: str | None
    extraction: dict[str, Any] | None
    validated_by_name: str | None
    validated_at: datetime | None
    duplicate: dict[str, Any] | None
    erp_system: str | None
    erp_ref: str | None
    posted_at: datetime | None
    match: dict[str, Any] | None
    match_runs: int
    released_at: datetime | None
    paid_at: datetime | None
    payment_ref: str | None
    rejected_reason: str | None
    lines: list[InvoiceLineOut]
    lines_total: Decimal
    exception: ExceptionOut | None
    receipt_requests: list[ReceiptRequestOut]
    can_edit: bool


class ReceiptPortalView(BaseModel):
    """What the receiver sees on the phone (3.6.2)."""

    status: str  # open / used / expired
    organisation: str
    po_reference: str
    vendor_name: str
    receiver_name: str | None
    invoice_reference: str | None
    lines: list[dict[str, Any]]  # position, description, ordered, already received, unit
