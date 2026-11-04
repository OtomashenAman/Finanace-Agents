import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class ApplicationStatus(StrEnum):
    INVITED = "invited"  # the portal link went out; waiting for the client (1.1.1)
    NEEDS_INFO = "needs_info"  # the onboarding agent sent the client its gaps (1.1.2.c)
    SUBMITTED = "submitted"  # checked; client services clears what the agent flagged
    PROPOSED = "proposed"  # the credit agent proposed terms; the credit controller decides
    ACTIVE = "active"  # approved; the account agent created the account in both systems
    REJECTED = "rejected"


class FpClientApplication(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One client's account application (AR Phase 1.1-1.2). Credit is granted only by the
    credit controller's decision on it."""

    __tablename__ = "fpod_client_applications"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", ApplicationStatus),)

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        string_enum(ApplicationStatus, 16), index=True
    )
    client_name: Mapped[str] = mapped_column(String(200))
    client_email: Mapped[str] = mapped_column(String(320))
    # The portal link: only its SHA-256 is kept; it works once, until it expires
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None]
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    invited_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]  # first submission (set-up time starts at invite)
    submissions: Mapped[int] = mapped_column(default=0, server_default="0")

    # What the client entered on the portal (1.1.1)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    country: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(200))
    billing_email: Mapped[str | None] = mapped_column(String(320))
    # [{name, email, phone, role}]
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    currency: Mapped[str | None] = mapped_column(String(3))
    requested_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    requested_terms: Mapped[str | None] = mapped_column(String(40))
    expected_monthly: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    years_trading: Mapped[int | None]

    # The onboarding agent: what it read in the documents, its checks, the gaps it sent
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    agent_ran_at: Mapped[datetime | None]
    cleared: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    gaps: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # Issues the agent found in the first submission (a data-error measure)
    first_issues: Mapped[int | None]

    # The credit agent's proposal (1.2.1): score, risk, decision, limit or deposit, reasons
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    proposed_at: Mapped[datetime | None]

    # The credit controller's decision (1.2.2)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)
    changed_from_proposal: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_clients.id", ondelete="SET NULL")
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text)

    @property
    def reference(self) -> str:
        return f"APP-{self.number:04d}"


class ClientDocumentKind(StrEnum):
    REGISTRATION = "registration"  # certificate of incorporation / business registration
    TAX = "tax"  # W-9 or the country's tax registration
    CREDIT_REPORT = "credit_report"
    TRADE_REFERENCE = "trade_reference"
    OTHER = "other"


class FpClientDocument(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "fpod_client_documents"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("application_id", "sha256"),
        enum_check("kind", ClientDocumentKind),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_client_applications.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ClientDocumentKind] = mapped_column(string_enum(ClientDocumentKind, 20))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(150))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ClientStatus(StrEnum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"  # new work only against a deposit, until the controller says otherwise


class FpClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A client account: the ERP side of the record (local ERP: this row). Its credit terms
    change only by a credit controller's approval."""

    __tablename__ = "fpod_clients"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", ClientStatus),)

    code: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[ClientStatus] = mapped_column(string_enum(ClientStatus, 16))
    version: Mapped[int] = mapped_column(default=1)
    name: Mapped[str] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    country: Mapped[str | None] = mapped_column(String(2))
    address: Mapped[str | None] = mapped_column(Text)
    billing_email: Mapped[str] = mapped_column(String(320))
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    currency: Mapped[str] = mapped_column(String(3))
    # None with deposit_pct > 0: deposit only, no credit
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    deposit_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    payment_terms: Mapped[str] = mapped_column(String(40))
    risk: Mapped[str | None] = mapped_column(String(10))  # low / medium / high, at the decision
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    erp_ref: Mapped[str | None] = mapped_column(String(100))
    lab_ref: Mapped[str | None] = mapped_column(String(100))
    synced_at: Mapped[datetime | None]
    # Times the monitor found the lab system out of line with the ERP and corrected it
    sync_fixes: Mapped[int] = mapped_column(default=0, server_default="0")
    last_reviewed_at: Mapped[datetime | None]
    next_review_on: Mapped[date | None]


class FpLabClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The lab system's client register (local stand-in for a LIMS). The account agent
    writes it from the ERP record; nobody keys a client in twice."""

    __tablename__ = "fpod_lab_clients"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    lab_code: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. LAB-C-00001
    client_code: Mapped[str] = mapped_column(String(40), unique=True)  # the ERP's code
    name: Mapped[str] = mapped_column(String(200))
    billing_email: Mapped[str] = mapped_column(String(320))
    currency: Mapped[str] = mapped_column(String(3))
    # What the lab may accept work on: "credit" (within the limit), "deposit", "hold"
    work_status: Mapped[str] = mapped_column(String(10))
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    deposit_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))


class FpClientHistory(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A client's billing and payment history (an invoice, and when it was paid): what the
    monitor reviews limits from. Imported for now; later AR phases write it as they bill."""

    __tablename__ = "fpod_client_history"
    __table_args__ = (UniqueConstraint("client_code", "invoice_number"),)

    client_code: Mapped[str] = mapped_column(String(40), index=True)
    invoice_number: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    issued_on: Mapped[date]
    due_on: Mapped[date]
    paid_on: Mapped[date | None]


class ReviewStatus(StrEnum):
    PROPOSED = "proposed"  # the monitor proposed a change; the credit controller decides
    APPROVED = "approved"
    DISMISSED = "dismissed"


class FpCreditReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The monitor's review of a client's terms as history builds (1.3.2). A change to
    credit takes effect only when the credit controller approves it."""

    __tablename__ = "fpod_credit_reviews"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", ReviewStatus),)

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_clients.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ReviewStatus] = mapped_column(string_enum(ReviewStatus, 16), index=True)
    trigger: Mapped[str] = mapped_column(String(20))  # history / periodic
    # {metrics, current: {...}, proposed: {...}, reasons: [...]}
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)

    @property
    def reference(self) -> str:
        return f"CR-{self.number:04d}"
