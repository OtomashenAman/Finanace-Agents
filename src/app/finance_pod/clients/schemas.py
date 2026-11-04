import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from src.app.finance_pod.clients.models import (
    ApplicationStatus,
    ClientDocumentKind,
    ClientStatus,
    ReviewStatus,
)


class InviteIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    client_email: EmailStr


class ClearIn(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=5, max_length=1000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class Terms(BaseModel):
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    deposit_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    payment_terms: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")


class DecisionIn(Terms):
    """The credit controller's decision: approve these terms (as proposed or changed)."""

    note: str = Field(default="", max_length=2000)


class ReviewDecisionIn(BaseModel):
    approve: bool
    # Approve with changes: the terms the controller sets instead of the proposal's
    terms: Terms | None = None
    status: Literal["active", "on_hold"] | None = None
    note: str = Field(default="", max_length=2000)


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str = Field(default="", max_length=40)
    role: str = Field(default="", max_length=80)


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: ClientDocumentKind
    filename: str
    content_type: str
    size: int
    created_at: datetime


class ApplicationSummary(BaseModel):
    id: uuid.UUID
    reference: str
    status: ApplicationStatus
    client_name: str
    client_email: str
    invited_at: datetime | None
    submitted_at: datetime | None
    open_issues: int | None  # None: not checked yet
    risk: str | None
    client_code: str | None


class ApplicationOut(ApplicationSummary):
    token_expires_at: datetime | None
    submissions: int
    legal_name: str | None
    tax_id: str | None
    country: str | None
    address: str | None
    phone: str | None
    website: str | None
    billing_email: str | None
    contacts: list[dict[str, Any]]
    currency: str | None
    requested_limit: Decimal | None
    requested_terms: str | None
    expected_monthly: Decimal | None
    years_trading: int | None
    extraction: dict[str, Any] | None
    checks: list[dict[str, Any]]
    cleared: list[dict[str, Any]]
    gaps: list[str]
    agent_ran_at: datetime | None
    proposal: dict[str, Any] | None
    proposed_at: datetime | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    changed_from_proposal: bool
    client_id: uuid.UUID | None
    rejected_reason: str | None
    invited_by_name: str | None
    documents: list[DocumentOut]
    can_decide: str | None  # None: the viewer may decide now; else why not
    portal_url: str | None  # right after a link was issued (shown once)


class SyncState(BaseModel):
    in_sync: bool
    differences: list[str]  # "credit limit: ERP 25,000.00, lab 20,000.00"


class ClientOut(BaseModel):
    id: uuid.UUID
    code: str
    status: ClientStatus
    version: int
    name: str
    tax_id: str | None
    country: str | None
    address: str | None
    billing_email: str
    contacts: list[dict[str, Any]]
    currency: str
    credit_limit: Decimal | None
    deposit_pct: Decimal
    payment_terms: str
    risk: str | None
    erp_ref: str | None
    lab_ref: str | None
    synced_at: datetime | None
    sync: SyncState
    last_reviewed_at: datetime | None
    next_review_on: date | None
    approved_by_name: str | None
    application_id: uuid.UUID | None
    history: dict[str, Any]
    open_review_id: uuid.UUID | None
    created_at: datetime


class ReviewOut(BaseModel):
    id: uuid.UUID
    reference: str
    client_id: uuid.UUID
    client_code: str
    client_name: str
    currency: str
    status: ReviewStatus
    trigger: str
    proposal: dict[str, Any]
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class MonitorResult(BaseModel):
    reviewed: int
    proposed: int  # new reviews for the credit controller
    resynced: int  # lab records put back in line with the ERP


class HistoryImport(BaseModel):
    rows: int
    clients: int
    skipped: list[str]
    monitor: MonitorResult


class PortalView(BaseModel):
    client_name: str
    status: Literal["open", "used", "expired"]
    expires_at: datetime | None
    organisation: str
    gaps: list[str]  # what to fix, when the agent sent the client back
    documents_held: list[ClientDocumentKind]  # already received: no need to send again
    previous: dict[str, Any]  # the last answers, to correct rather than retype
