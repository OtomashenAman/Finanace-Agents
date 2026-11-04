import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from src.app.finance_pod.mail import MailKind, MailStatus
from src.app.finance_pod.sourcing.models import QuoteStatus, SourcingStatus


class Candidate(BaseModel):
    """A vendor the sourcing agent found (1.3.1.a)."""

    vendor_code: str
    vendor_name: str
    vendor_email: str | None
    reasons: list[str]
    contract_lines: list[int]  # request lines this vendor has a contract price for
    contract_total: Decimal | None  # those lines at contract prices
    covers_all_lines: bool


class VendorRef(BaseModel):
    """An approved vendor by code, or a new one by name and email."""

    vendor_code: str | None = Field(default=None, max_length=40)
    vendor_name: str | None = Field(default=None, max_length=200)
    vendor_email: EmailStr | None = None

    @model_validator(mode="after")
    def _one_way(self) -> "VendorRef":
        if not self.vendor_code and not (self.vendor_name and self.vendor_email):
            raise ValueError("give a vendor code, or a new vendor's name and email")
        return self


class QuoteRequestIn(BaseModel):
    vendors: list[VendorRef] = Field(min_length=1, max_length=10)
    reply_by: date
    message: str = Field(default="", max_length=2000)


class QuoteIn(BaseModel):
    """A quote as received (typed by the buyer, or confirmed after the agent read it)."""

    status: QuoteStatus = QuoteStatus.RECEIVED
    total: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    payment_terms: str | None = Field(default=None, max_length=200)
    valid_until: date | None = None
    notes: str | None = Field(default=None, max_length=4000)


class NewQuoteIn(QuoteIn, VendorRef):
    pass


class ChooseIn(BaseModel):
    """The buyer's choice (1.3.2): a received quote, or a contract vendor's prices."""

    quote_id: uuid.UUID | None = None
    contract_vendor_code: str | None = Field(default=None, max_length=40)
    payment_terms: str = Field(min_length=1, max_length=200)
    delivery_date: date | None = None
    justification: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _one_way(self) -> "ChooseIn":
        if bool(self.quote_id) == bool(self.contract_vendor_code):
            raise ValueError("choose a quote or a contract vendor (one of them)")
        return self


class QuoteOut(BaseModel):
    id: uuid.UUID
    vendor_code: str | None
    vendor_name: str
    vendor_email: str | None
    status: QuoteStatus
    requested_at: datetime | None
    received_at: datetime | None
    total: Decimal | None
    currency: str | None
    lead_time_days: int | None
    payment_terms: str | None
    valid_until: date | None
    notes: str | None
    filename: str | None
    ai_read: dict[str, object] | None


class ComparisonRow(BaseModel):
    """One quote or contract option side by side (1.3.1.c). Flags are computed, never AI."""

    option: str  # "quote" / "contract"
    quote_id: uuid.UUID | None
    vendor_code: str | None
    vendor_name: str
    total: Decimal
    vs_estimate: Decimal  # total - the request's estimate
    lead_time_days: int | None
    arrives_by: date | None
    meets_needed_by: bool | None
    payment_terms: str | None
    valid_until: date | None
    expired: bool
    new_vendor: bool
    flags: list[str]  # lowest price, fastest, contract vendor...


class EmailOut(BaseModel):
    id: uuid.UUID
    kind: MailKind
    to_email: str
    subject: str
    body: str
    status: MailStatus
    simulated: bool
    error: str | None
    created_at: datetime


class SourcingOut(BaseModel):
    status: SourcingStatus
    quotes_needed: int
    quotes_received: int
    candidates: list[Candidate]
    quotes: list[QuoteOut]
    comparison: list[ComparisonRow]
    chosen_quote_id: uuid.UUID | None
    chosen_vendor_code: str | None
    chosen_vendor_name: str | None
    chosen_total: Decimal | None
    payment_terms: str | None
    delivery_date: date | None
    justification: str | None
    onboarding_id: uuid.UUID | None
    decided_at: datetime | None
    decided_by_name: str | None
    can_change: bool  # no PO yet
    emails: list[EmailOut]
