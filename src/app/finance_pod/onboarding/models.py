import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, String, Text, UniqueConstraint, text
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


class OnboardingKind(StrEnum):
    NEW_VENDOR = "new_vendor"
    BANK_CHANGE = "bank_change"  # an existing vendor's new bank details: same checks


class OnboardingStatus(StrEnum):
    INVITED = "invited"  # the portal link went out; waiting for the vendor
    SUBMITTED = "submitted"  # the vendor sent documents; the agent read them (1.5.1)
    VERIFIED = "verified"  # the AP analyst called back and confirmed the bank (1.5.2.a)
    ACTIVE = "active"  # a second approver activated the vendor (1.5.2.b)
    REJECTED = "rejected"


class FpOnboarding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Onboarding one vendor (Phase 1.5). Bank details only ever arrive through the portal
    and take effect only after the call-back and a second person's activation."""

    __tablename__ = "fpod_onboardings"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("kind", OnboardingKind), enum_check("status", OnboardingStatus))

    kind: Mapped[OnboardingKind] = mapped_column(string_enum(OnboardingKind, 16))
    status: Mapped[OnboardingStatus] = mapped_column(string_enum(OnboardingStatus, 16))
    vendor_name: Mapped[str] = mapped_column(String(200))
    vendor_email: Mapped[str] = mapped_column(String(320))
    vendor_code: Mapped[str | None] = mapped_column(String(40))  # existing (bank change) / new
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="SET NULL"), index=True
    )
    # The portal link: only its SHA-256 is kept; it works once, until it expires
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None]
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    invited_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]

    # What the vendor entered on the portal (account and routing numbers encrypted)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(40))
    tax_form: Mapped[str | None] = mapped_column(String(10))  # W-9 / W-8BEN / W-8BEN-E
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))  # as given: never used to call back
    bank_name: Mapped[str | None] = mapped_column(String(200))
    account_name: Mapped[str | None] = mapped_column(String(200))
    routing_number_enc: Mapped[str | None] = mapped_column(Text)
    account_number_enc: Mapped[str | None] = mapped_column(Text)
    account_last4: Mapped[str | None] = mapped_column(String(4))

    # The onboarding agent's reading of the documents and its checks (1.5.1.b-c)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    agent_ran_at: Mapped[datetime | None]
    # Warnings an analyst cleared, with why (e.g. a sanctions false positive)
    cleared: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )

    # The AP analyst's call-back (1.5.2.a)
    callback_phone: Mapped[str | None] = mapped_column(String(40))
    callback_source: Mapped[str | None] = mapped_column(String(120))
    callback_contact: Mapped[str | None] = mapped_column(String(200))
    callback_notes: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    verified_at: Mapped[datetime | None]
    # The second approver (1.5.2.b)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    activated_at: Mapped[datetime | None]
    erp_ref: Mapped[str | None] = mapped_column(String(100))
    rejected_reason: Mapped[str | None] = mapped_column(Text)


class DocumentKind(StrEnum):
    TAX_FORM = "tax_form"
    BANK_LETTER = "bank_letter"
    INSURANCE = "insurance"
    OTHER = "other"


class FpOnboardingDocument(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "fpod_onboarding_documents"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("onboarding_id", "sha256"),
        enum_check("kind", DocumentKind),
    )

    onboarding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_onboardings.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(string_enum(DocumentKind, 16))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(150))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class FpVendorBankAccount(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A vendor's bank account, in force once activated. A change is a new onboarding (bank
    change) and a new row; the old row is retired, never edited."""

    __tablename__ = "fpod_vendor_bank_accounts"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    vendor_code: Mapped[str] = mapped_column(String(40), index=True)
    onboarding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_onboardings.id", ondelete="RESTRICT")
    )
    bank_name: Mapped[str] = mapped_column(String(200))
    account_name: Mapped[str] = mapped_column(String(200))
    routing_number_enc: Mapped[str] = mapped_column(Text)
    account_number_enc: Mapped[str] = mapped_column(Text)
    account_last4: Mapped[str] = mapped_column(String(4))
    retired_at: Mapped[datetime | None]


class FpSanctionsEntry(UUIDPrimaryKeyMixin, Base):
    """One name on the sanctions list (OFAC SDN), normalized for screening."""

    __tablename__ = "fpod_sanctions_entries"

    name: Mapped[str] = mapped_column(String(400))
    normalized: Mapped[str] = mapped_column(String(400), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    program: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40))  # e.g. "OFAC SDN"
    list_ref: Mapped[str | None] = mapped_column(String(40))  # the list's own ID
    loaded_at: Mapped[datetime]
