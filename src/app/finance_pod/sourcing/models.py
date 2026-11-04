import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class SourcingStatus(StrEnum):
    OPEN = "open"  # finding vendors, collecting quotes
    AWAITING_VENDOR = "awaiting_vendor"  # the chosen vendor is being onboarded (1.5)
    CHOSEN = "chosen"  # vendor and terms confirmed: the PO can be drafted (1.6)


class FpSourcing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Vendor selection for one approved request (Phase 1.3)."""

    __tablename__ = "fpod_sourcing"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", SourcingStatus),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[SourcingStatus] = mapped_column(
        string_enum(SourcingStatus, 24), default=SourcingStatus.OPEN
    )
    # The sourcing agent's findings: approved vendors and contract matches (1.3.1.a)
    candidates: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    quotes_needed: Mapped[int] = mapped_column(default=0)
    # The buyer's choice (1.3.2)
    chosen_quote_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_quotes.id", ondelete="SET NULL", use_alter=True)
    )
    chosen_vendor_code: Mapped[str | None] = mapped_column(String(40))
    chosen_vendor_name: Mapped[str | None] = mapped_column(String(200))
    chosen_vendor_email: Mapped[str | None] = mapped_column(String(320))
    chosen_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    delivery_date: Mapped[date | None]
    # Why fewer quotes than required (sole source, contract purchase...)
    justification: Mapped[str | None] = mapped_column(Text)
    onboarding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_onboardings.id", ondelete="SET NULL", use_alter=True)
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None]


class QuoteStatus(StrEnum):
    REQUESTED = "requested"  # the quote request went out; no answer yet
    RECEIVED = "received"
    DECLINED = "declined"  # the vendor won't quote


class FpQuote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fpod_quotes"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", QuoteStatus),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), index=True
    )
    vendor_code: Mapped[str | None] = mapped_column(String(40))  # None: not in vendor master
    vendor_name: Mapped[str] = mapped_column(String(200))
    vendor_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[QuoteStatus] = mapped_column(string_enum(QuoteStatus, 16))
    requested_at: Mapped[datetime | None]
    received_at: Mapped[datetime | None]
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    lead_time_days: Mapped[int | None]
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    valid_until: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)
    # The quote document, and what the sourcing agent read from it (checked against its text)
    filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(150))
    sha256: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    ai_read: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
