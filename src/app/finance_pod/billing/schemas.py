import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.app.finance_pod.billing.models import (
    OverrideStatus,
    SalesInvoiceStatus,
    SubmissionStatus,
)

Turnaround = Literal["standard", "express", "rush"]


class SubmissionLineIn(BaseModel):
    item_ref: str = Field(min_length=1, max_length=80)
    stone_type: str = Field(min_length=1, max_length=40)
    carat: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    service_code: str = Field(min_length=1, max_length=40)
    quantity: int = Field(default=1, ge=1, le=10000)
    special_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    special_reason: str | None = Field(default=None, max_length=1000)


class SubmissionIn(BaseModel):
    client_code: str = Field(min_length=1, max_length=40)
    turnaround: Turnaround = "standard"
    received_on: date | None = None
    estimate: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    external_ref: str | None = Field(default=None, max_length=80)
    lines: list[SubmissionLineIn] = Field(min_length=1, max_length=500)


class PerformedIn(BaseModel):
    """A service the lab performed. One not on the submission is an added service."""

    item_ref: str = Field(min_length=1, max_length=80)
    service_code: str = Field(min_length=1, max_length=40)
    stone_type: str | None = Field(default=None, max_length=40)
    carat: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=3)
    quantity: int = Field(default=1, ge=1, le=10000)


class ReportIssuedIn(BaseModel):
    # Omitted: every requested service was performed
    performed: list[PerformedIn] | None = Field(default=None, max_length=500)


class LabEventIn(BaseModel):
    """What a lab system sends: a submission received, or its report issued."""

    event: Literal["submission_received", "report_issued"]
    submission: str = Field(min_length=1, max_length=80)  # the lab's ref, or SUB-00012
    received: SubmissionIn | None = None  # for submission_received
    performed: list[PerformedIn] | None = None  # for report_issued


class SubmissionLineOut(BaseModel):
    id: uuid.UUID
    position: int
    item_ref: str
    stone_type: str
    carat: Decimal | None
    service_code: str
    quantity: int
    requested: bool
    performed: bool
    special_price: Decimal | None
    special_reason: str | None


class SubmissionOut(BaseModel):
    id: uuid.UUID
    reference: str
    external_ref: str | None
    client_code: str
    client_name: str | None
    status: SubmissionStatus
    turnaround: str
    received_on: date
    estimate: Decimal | None
    notes: str | None
    report_issued_at: datetime | None
    issued_via: str | None
    lines: list[SubmissionLineOut]
    invoice_id: uuid.UUID | None
    invoice_reference: str | None
    created_at: datetime


class InvoiceLineOut(BaseModel):
    id: uuid.UUID
    position: int
    item_ref: str
    service_code: str
    description: str
    stone_type: str
    carat: Decimal | None
    quantity: int
    list_price: Decimal | None
    unit_price: Decimal
    price_source: str
    price_note: str | None
    amount: Decimal
    flags: list[dict[str, Any]]
    override_price: Decimal | None
    override_reason: str | None
    override_status: OverrideStatus | None
    override_by_name: str | None  # None with a pending override: from the intake record
    override_decided_by_name: str | None


class InvoiceSummary(BaseModel):
    id: uuid.UUID
    reference: str
    status: SalesInvoiceStatus
    client_code: str
    client_name: str
    submission_reference: str
    currency: str
    total: Decimal
    estimate: Decimal | None
    open_items: list[str]
    built_at: datetime
    sent_at: datetime | None


class InvoiceOut(InvoiceSummary):
    version: int
    submission_id: uuid.UUID
    client_id: uuid.UUID
    bill_to_email: str
    payment_terms: str
    deposit_pct: Decimal
    subtotal: Decimal
    discount_total: Decimal
    tax_name: str | None
    tax_rate: Decimal
    tax: Decimal
    flags: list[dict[str, Any]]
    lines: list[InvoiceLineOut]
    flagged_on_build: bool
    corrected: bool
    approved_by_name: str | None
    approved_at: datetime | None
    issue_date: date | None
    due_date: date | None
    erp_ref: str | None
    viewed_at: datetime | None
    void_reason: str | None
    report_issued_at: datetime | None


class OverrideIn(BaseModel):
    line_id: uuid.UUID
    price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    reason: str = Field(min_length=3, max_length=1000)


class OverrideDecisionIn(BaseModel):
    line_id: uuid.UUID
    approve: bool
    note: str = Field(default="", max_length=1000)


class ClearFlagIn(BaseModel):
    line_id: uuid.UUID | None = None  # None: a flag on the invoice as a whole
    key: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=3, max_length=1000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class FeeOut(BaseModel):
    service_code: str
    service_name: str
    stone_type: str | None
    carat_from: Decimal | None
    carat_to: Decimal | None
    turnaround: str
    fee: Decimal
    currency: str


class ContractOut(BaseModel):
    client_code: str
    service_code: str
    price: Decimal | None
    discount_pct: Decimal | None
    contract_ref: str | None
    valid_to: date | None


class TaxOut(BaseModel):
    country: str
    region: str | None
    name: str
    rate_pct: Decimal


class FeeScheduleOut(BaseModel):
    fees: list[FeeOut]
    contracts: list[ContractOut]
    taxes: list[TaxOut]


class ImportResult(BaseModel):
    submissions: int
    issued: int  # of them, with the report issued (invoices built)
    errors: list[str]


class StatementOut(BaseModel):
    client_code: str
    period: str
    open_balance: Decimal
    open_invoices: int
    created_at: datetime


class PublicInvoiceView(BaseModel):
    organisation: str
    reference: str
    client_name: str
    client_code: str
    submission_reference: str
    issue_date: date | None
    due_date: date | None
    payment_terms: str
    currency: str
    lines: list[dict[str, Any]]
    subtotal: Decimal
    discount_total: Decimal
    tax_name: str | None
    tax_rate: Decimal
    tax: Decimal
    total: Decimal
    status: Literal["open", "void"]
