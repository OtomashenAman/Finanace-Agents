import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class RunStatus(StrEnum):
    PROPOSED = "proposed"  # the payment agent proposed it; analyst checks, treasury reviews
    PARTLY_APPROVED = "partly_approved"  # one of the two releases given
    RELEASED = "released"  # both released: paid, remittances sent
    CANCELLED = "cancelled"


class FpPaymentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A payment run. Agents propose and post; only two different people release it."""

    __tablename__ = "fpod_payment_runs"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", RunStatus),)

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    status: Mapped[RunStatus] = mapped_column(string_enum(RunStatus, 20), index=True)
    version: Mapped[int] = mapped_column(default=1)
    run_date: Mapped[date]
    horizon_days: Mapped[int]
    cash_available: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # at proposal
    proposed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    released_at: Mapped[datetime | None]
    cancelled_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["FpPaymentItem"]] = relationship(
        order_by="FpPaymentItem.position", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def reference(self) -> str:
        return f"PAY-{self.number:04d}"


class CallbackStatus(StrEnum):
    NOT_NEEDED = "not_needed"
    NEEDED = "needed"  # bank details changed lately: the analyst calls back first
    CONFIRMED = "confirmed"


class FpPaymentItem(UUIDPrimaryKeyMixin, Base):
    """One invoice in a run, with the risk checks on it."""

    __tablename__ = "fpod_payment_items"
    __table_args__ = (enum_check("callback_status", CallbackStatus),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_payment_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_invoices.id", ondelete="RESTRICT"), index=True
    )
    vendor_code: Mapped[str] = mapped_column(String(40))
    vendor_name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    bank_name: Mapped[str | None] = mapped_column(String(200))
    account_last4: Mapped[str | None] = mapped_column(String(4))
    group_key: Mapped[str] = mapped_column(String(240))  # currency and bank
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # what's paid
    due_date: Mapped[date]
    discount_until: Mapped[date | None]
    reason: Mapped[str] = mapped_column(String(20))  # due / overdue / discount
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    callback_status: Mapped[CallbackStatus] = mapped_column(
        string_enum(CallbackStatus, 16), default=CallbackStatus.NOT_NEEDED
    )
    callback_note: Mapped[str | None] = mapped_column(Text)
    callback_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    callback_at: Mapped[datetime | None]
    excluded: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    exclude_reason: Mapped[str | None] = mapped_column(Text)
    payment_ref: Mapped[str | None] = mapped_column(String(40))


class FpPaymentApproval(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One of the two releases a run needs (treasury, dual approval)."""

    __tablename__ = "fpod_payment_approvals"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_payment_runs.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    note: Mapped[str] = mapped_column(Text, default="")
    self_approval: Mapped[bool] = mapped_column(default=False, server_default=text("false"))


class QueryIntent(StrEnum):
    STATUS = "status"  # where's my payment / invoice
    MISSING_INVOICE = "missing_invoice"  # did you get my invoice
    DISPUTE = "dispute"  # disagreement: short payment, deduction, rejection
    OTHER = "other"


class QueryStatus(StrEnum):
    ANSWERED = "answered"  # the vendor agent answered from the records
    ESCALATED = "escalated"  # a dispute or something the agent can't answer: analyst
    RESOLVED = "resolved"  # the analyst replied


class FpVendorQuery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fpod_vendor_queries"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("intent", QueryIntent), enum_check("status", QueryStatus))

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    via: Mapped[str] = mapped_column(String(20))  # portal / app
    from_email: Mapped[str] = mapped_column(String(320))
    vendor_code: Mapped[str | None] = mapped_column(String(40))  # matched by its email on file
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    invoice_number: Mapped[str | None] = mapped_column(String(80))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_invoices.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[QueryIntent] = mapped_column(string_enum(QueryIntent, 20))
    intent_source: Mapped[str] = mapped_column(String(10))  # ai / keywords
    status: Mapped[QueryStatus] = mapped_column(string_enum(QueryStatus, 16), index=True)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )  # None: the vendor agent
    answered_at: Mapped[datetime | None]
    escalation_reason: Mapped[str | None] = mapped_column(Text)

    @property
    def reference(self) -> str:
        return f"Q-{self.number:04d}"
