import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from src.app.finance_pod.orders.models import PoStatus


class PoLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    category: str | None = Field(default=None, max_length=64)


class PoUpdate(BaseModel):
    expected_version: int
    lines: list[PoLineIn] = Field(min_length=1, max_length=100)
    payment_terms: str | None = Field(default=None, max_length=200)
    delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class VersionIn(BaseModel):
    expected_version: int


class ReasonIn(VersionIn):
    reason: str = Field(min_length=3, max_length=1000)


class PoLineOut(BaseModel):
    description: str
    quantity: Decimal
    unit: str | None
    unit_price: Decimal
    category: str | None
    catalogue_item_code: str | None
    price_source: str
    amount: Decimal


class PoIssue(BaseModel):
    message: str
    blocking: bool


class PoOut(BaseModel):
    id: uuid.UUID
    reference: str
    request_id: uuid.UUID
    request_reference: str
    status: PoStatus
    version: int
    vendor_code: str
    vendor_name: str
    vendor_email: str | None
    currency: str
    total: Decimal
    quote_total: Decimal | None
    payment_terms: str | None
    delivery_date: date | None
    cost_centre_code: str | None
    lab_code: str | None
    project_code: str | None
    grant_code: str | None
    notes: str | None
    lines: list[PoLineOut]
    issues: list[PoIssue]  # from the PO agent's checks
    drafted_by_name: str
    approval_capacity: str | None
    approver_email: str | None
    approved_by_name: str | None
    approved_at: datetime | None
    approval_acting_for: str | None
    self_approval: bool
    issued_at: datetime | None
    erp_system: str | None
    erp_ref: str | None
    acknowledged_at: datetime | None
    acknowledgement_note: str | None
    acknowledgement_filename: str | None
    cancelled_reason: str | None
    created_at: datetime
    can_approve: str | None  # None: the viewer can approve now; else why not


class PoSummary(BaseModel):
    id: uuid.UUID
    reference: str
    request_id: uuid.UUID
    request_reference: str
    status: PoStatus
    vendor_name: str
    total: Decimal
    currency: str
    issued_at: datetime | None
    created_at: datetime
