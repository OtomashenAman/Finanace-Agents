import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from src.app.finance_pod.onboarding.models import DocumentKind, OnboardingKind, OnboardingStatus

# Where the analyst got the number they called. Never from what the vendor just sent:
# a fraudster changing bank details supplies their own phone number too.
CALLBACK_SOURCES = (
    "vendor master / earlier records",
    "vendor's official website",
    "public directory",
    "contract or purchase history",
    "other independent source",
)


class InviteIn(BaseModel):
    vendor_name: str = Field(min_length=1, max_length=200)
    vendor_email: EmailStr
    request_id: uuid.UUID | None = None


class BankChangeIn(BaseModel):
    vendor_code: str = Field(min_length=1, max_length=40)
    vendor_email: EmailStr | None = None  # default: the vendor master's


class ClearIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=5, max_length=1000)


class CallbackIn(BaseModel):
    """The AP analyst's call-back to confirm the bank details (1.5.2.a)."""

    phone: str = Field(min_length=5, max_length=40)
    source: Literal[CALLBACK_SOURCES]  # type: ignore[valid-type]
    contact: str = Field(min_length=2, max_length=200)
    confirmed_last4: str = Field(pattern=r"^\d{4}$")
    notes: str = Field(default="", max_length=2000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: DocumentKind
    filename: str
    content_type: str
    size: int
    created_at: datetime


class OnboardingSummary(BaseModel):
    id: uuid.UUID
    kind: OnboardingKind
    status: OnboardingStatus
    vendor_name: str
    vendor_email: str
    vendor_code: str | None
    request_id: uuid.UUID | None
    request_reference: str | None
    invited_at: datetime | None
    submitted_at: datetime | None
    open_issues: int | None


class OnboardingOut(OnboardingSummary):
    token_expires_at: datetime | None
    legal_name: str | None
    tax_id: str | None
    tax_form: str | None
    address: str | None
    phone: str | None
    bank_name: str | None
    account_name: str | None
    routing_masked: str | None
    account_masked: str | None
    extraction: dict[str, Any] | None
    checks: list[dict[str, Any]]
    cleared: list[dict[str, Any]]
    agent_ran_at: datetime | None
    callback_phone: str | None
    callback_source: str | None
    callback_contact: str | None
    callback_notes: str | None
    verified_by_name: str | None
    verified_at: datetime | None
    activated_by_name: str | None
    activated_at: datetime | None
    erp_ref: str | None
    rejected_reason: str | None
    documents: list[DocumentOut]
    can_verify: str | None  # None: can; else why not
    can_activate: str | None
    portal_url: str | None  # only right after an invite (the token isn't stored)


class PortalView(BaseModel):
    vendor_name: str
    kind: OnboardingKind
    status: Literal["open", "used", "expired"]
    expires_at: datetime | None
    organisation: str


class SanctionsInfo(BaseModel):
    entries: int
    loaded_at: str | None
    source_url: str
