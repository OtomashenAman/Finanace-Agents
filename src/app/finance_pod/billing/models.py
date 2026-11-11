import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
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

# --- the fee schedule: changed only by an admin's workbook upload, never by an agent ---------


class FpFee(UUIDPrimaryKeyMixin, Base):
    """One published fee: a service for a stone type, a carat band and a turnaround."""

    __tablename__ = "fpod_fees"
    __table_args__ = (
        UniqueConstraint(
            "service_code",
            "stone_type",
            "carat_from",
            "turnaround",
            postgresql_nulls_not_distinct=True,
        ),
    )

    service_code: Mapped[str] = mapped_column(String(40), index=True)
    service_name: Mapped[str] = mapped_column(String(200))
    stone_type: Mapped[str | None] = mapped_column(String(40))  # None: any stone
    carat_from: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # None: any weight
    carat_to: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))  # below this
    turnaround: Mapped[str] = mapped_column(String(20))  # standard / express / rush
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))


class FpContractPrice(UUIDPrimaryKeyMixin, Base):
    """A client's contract price for a service: a fixed unit price, or a discount off the
    published fee."""

    __tablename__ = "fpod_contract_prices"
    __table_args__ = (UniqueConstraint("client_code", "service_code"),)

    client_code: Mapped[str] = mapped_column(String(40), index=True)
    service_code: Mapped[str] = mapped_column(String(40))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    contract_ref: Mapped[str | None] = mapped_column(String(80))
    valid_to: Mapped[date | None]


class FpTaxRate(UUIDPrimaryKeyMixin, Base):
    """Tax by client location: a country, or a state/region within it."""

    __tablename__ = "fpod_tax_rates"
    __table_args__ = (UniqueConstraint("country", "region", postgresql_nulls_not_distinct=True),)

    country: Mapped[str] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(10))  # e.g. NY; None: the whole country
    name: Mapped[str] = mapped_column(String(80))
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(6, 3))


# --- lab submissions (the lab system's side; local register until a LIMS is connected) ------


class SubmissionStatus(StrEnum):
    IN_LAB = "in_lab"
    REPORT_ISSUED = "report_issued"  # the billing agent builds the invoice on this event
    INVOICED = "invoiced"
    CANCELLED = "cancelled"


class FpLabSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fpod_lab_submissions"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", SubmissionStatus),)

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    external_ref: Mapped[str | None] = mapped_column(String(80), unique=True)  # the LIMS's id
    client_code: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[SubmissionStatus] = mapped_column(string_enum(SubmissionStatus, 16), index=True)
    turnaround: Mapped[str] = mapped_column(String(20))
    received_on: Mapped[date]
    estimate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # quoted at intake
    notes: Mapped[str | None] = mapped_column(Text)
    report_issued_at: Mapped[datetime | None]
    issued_via: Mapped[str | None] = mapped_column(String(20))  # screen / import / api

    lines: Mapped[list["FpSubmissionLine"]] = relationship(
        order_by="FpSubmissionLine.position", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def reference(self) -> str:
        return f"SUB-{self.number:05d}"


class FpSubmissionLine(UUIDPrimaryKeyMixin, Base):
    """One service on one item. `requested`: asked for at intake; `performed`: done."""

    __tablename__ = "fpod_submission_lines"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_lab_submissions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    item_ref: Mapped[str] = mapped_column(String(80))
    stone_type: Mapped[str] = mapped_column(String(40))
    carat: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    service_code: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(default=1)
    requested: Mapped[bool] = mapped_column(default=True)
    performed: Mapped[bool] = mapped_column(default=False)
    # A special price agreed at intake (client services): an override the analyst approves
    special_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    special_reason: Mapped[str | None] = mapped_column(Text)


# --- client invoices ------------------------------------------------------------------------


class SalesInvoiceStatus(StrEnum):
    REVIEW = "review"  # flagged: the billing analyst reviews
    APPROVED = "approved"  # nothing open; the delivery agent sends it
    SENT = "sent"
    VOID = "void"


class FpSalesInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fpod_sales_invoices"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", SalesInvoiceStatus),)

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    status: Mapped[SalesInvoiceStatus] = mapped_column(
        string_enum(SalesInvoiceStatus, 16), index=True
    )
    version: Mapped[int] = mapped_column(default=1)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_lab_submissions.id", ondelete="RESTRICT"), unique=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_clients.id", ondelete="RESTRICT"), index=True
    )
    client_code: Mapped[str] = mapped_column(String(40))
    client_name: Mapped[str] = mapped_column(String(200))
    bill_to_email: Mapped[str] = mapped_column(String(320))
    currency: Mapped[str] = mapped_column(String(3))
    payment_terms: Mapped[str] = mapped_column(String(40))
    deposit_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    tax_name: Mapped[str | None] = mapped_column(String(80))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    estimate: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # The fee-rule agent's flags on the invoice as a whole: [{key, label, detail, cleared?}]
    flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    built_at: Mapped[datetime]
    flagged_on_build: Mapped[bool] = mapped_column(default=False)
    corrected: Mapped[bool] = mapped_column(default=False)  # a person changed a price
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None]
    issue_date: Mapped[date | None]
    due_date: Mapped[date | None]
    erp_ref: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None]
    # The client's link to view it online: only its SHA-256 is kept
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None]
    viewed_at: Mapped[datetime | None]
    void_reason: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["FpSalesInvoiceLine"]] = relationship(
        order_by="FpSalesInvoiceLine.position", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def reference(self) -> str:
        return f"SI-{self.number:05d}"


class OverrideStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FpSalesInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fpod_sales_invoice_lines"
    __table_args__ = (enum_check("override_status", OverrideStatus),)

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_sales_invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    item_ref: Mapped[str] = mapped_column(String(80))
    service_code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(300))
    stone_type: Mapped[str] = mapped_column(String(40))
    carat: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    quantity: Mapped[int]
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # the schedule's
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # what is charged
    # schedule / contract / override / none (not on the schedule)
    price_source: Mapped[str] = mapped_column(String(12))
    price_note: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # A price override: proposed (from intake or by a person), approved by the analyst
    override_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    override_reason: Mapped[str | None] = mapped_column(Text)
    override_status: Mapped[OverrideStatus | None] = mapped_column(string_enum(OverrideStatus, 16))
    override_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )  # None: from the intake record
    override_decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )


class FpStatement(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A client's monthly statement, sent by the delivery agent."""

    __tablename__ = "fpod_statements"
    __table_args__ = (UniqueConstraint("client_code", "period"),)

    client_code: Mapped[str] = mapped_column(String(40))
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM, the month it covers
    open_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    open_invoices: Mapped[int]
    email_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_emails.id", ondelete="SET NULL")
    )
