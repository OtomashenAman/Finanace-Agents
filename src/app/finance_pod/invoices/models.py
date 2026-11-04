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


class InvoiceStatus(StrEnum):
    CAPTURED = "captured"  # read from the document; AP confirms the data (3.1)
    DUPLICATE = "duplicate"  # blocked by the duplicate guard (3.2.2)
    POSTED = "posted"  # in the ERP; matching (3.2.1, 3.4)
    EXCEPTION = "exception"  # a variance or missing receipt is being resolved (3.5, 3.6)
    READY = "ready"  # matched (or variance resolved): released to coding (3.4.2.a)
    PAID = "paid"  # in a released payment run; remittance sent (Phase 5)
    REJECTED = "rejected"


class FpInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A supplier invoice (Phase 3). `version` grows with every change."""

    __tablename__ = "fpod_invoices"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", InvoiceStatus),)

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    status: Mapped[InvoiceStatus] = mapped_column(string_enum(InvoiceStatus, 16), index=True)
    version: Mapped[int] = mapped_column(default=1)
    vendor_code: Mapped[str | None] = mapped_column(String(40), index=True)
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    vendor_invoice_number: Mapped[str | None] = mapped_column(String(80))
    invoice_date: Mapped[date | None]
    due_date: Mapped[date | None]
    currency: Mapped[str] = mapped_column(String(3))
    tax_code: Mapped[str | None] = mapped_column(String(40))
    tax_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    po_reference: Mapped[str | None] = mapped_column(String(40))  # as printed on the invoice
    # The source document, and what the capture agent read from it
    filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(150))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    validated_at: Mapped[datetime | None]
    # The duplicate guard's finding (3.2.2), and a person's override of it
    duplicate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Posting (3.2.1)
    erp_system: Mapped[str | None] = mapped_column(String(20))
    erp_ref: Mapped[str | None] = mapped_column(String(100))
    posted_at: Mapped[datetime | None]
    # Matching (3.4): the last result, how many runs, and whether the first run matched
    match: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    match_runs: Mapped[int] = mapped_column(default=0)
    first_pass_matched: Mapped[bool | None]
    released_at: Mapped[datetime | None]  # to coding
    paid_at: Mapped[datetime | None]
    payment_ref: Mapped[str | None] = mapped_column(String(40))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    lines: Mapped[list["FpInvoiceLine"]] = relationship(
        order_by="FpInvoiceLine.position", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def reference(self) -> str:
        return f"INV-{self.number:05d}"

    @property
    def lines_total(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal("0.00"))


class FpInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fpod_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    po_line: Mapped[int | None]  # the PO line it bills, as stated or matched

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class ExceptionStatus(StrEnum):
    OPEN = "open"  # the buyer decides (3.5.2)
    WAITING_VENDOR = "waiting_vendor"  # a credit note was requested
    WAITING_RECEIPT = "waiting_receipt"  # the receiver confirms what arrived (3.6)
    RESOLVED = "resolved"


class ExceptionDecision(StrEnum):
    ACCEPT = "accept"  # accept the variance
    CREDIT = "credit"  # ask the vendor for a credit note
    AMEND_PO = "amend_po"  # the buyer amends the PO (the only way a PO price changes)
    REJECT = "reject"  # reject the invoice


class FpInvoiceException(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An invoice that didn't match (3.5): the exception agent's case, the buyer's decision."""

    __tablename__ = "fpod_invoice_exceptions"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        enum_check("status", ExceptionStatus),
        enum_check("decision", ExceptionDecision),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_invoices.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ExceptionStatus] = mapped_column(string_enum(ExceptionStatus, 20), index=True)
    kinds: Mapped[list[str]] = mapped_column(JSONB)  # price / quantity / no_receipt / ...
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    vendor_query_subject: Mapped[str | None] = mapped_column(String(300))
    vendor_query_body: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[ExceptionDecision | None] = mapped_column(string_enum(ExceptionDecision, 16))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(Text)
    credit_expected: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    credit_received: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    credit_note_ref: Mapped[str | None] = mapped_column(String(80))
    resolved_at: Mapped[datetime | None]


class FpPoAmendment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A buyer's change to a PO line, from an invoice exception. Agents never change a PO:
    this table records every change, with the old and the new value."""

    __tablename__ = "fpod_po_amendments"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    po_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_purchase_orders.id", ondelete="CASCADE"), index=True
    )
    exception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_invoice_exceptions.id", ondelete="SET NULL")
    )
    position: Mapped[int]
    old_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    new_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    old_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    new_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    note: Mapped[str] = mapped_column(Text)
    amended_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class FpReceipt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Goods or services received against a PO (the receiver's confirmation)."""

    __tablename__ = "fpod_receipts"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    po_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_purchase_orders.id", ondelete="CASCADE"), index=True
    )
    received_on: Mapped[date]
    receiver_email: Mapped[str | None] = mapped_column(String(320))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    via: Mapped[str] = mapped_column(String(20))  # mobile_link / app
    notes: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["FpReceiptLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class FpReceiptLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fpod_receipt_lines"

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_receipts.id", ondelete="CASCADE"), index=True
    )
    po_line: Mapped[int]  # the PO line's position
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class ReceiptRequestStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class FpReceiptRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The receipt agent's request to the receiver (3.6.1): a single-use mobile link."""

    __tablename__ = "fpod_receipt_requests"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", ReceiptRequestStatus),)

    po_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_purchase_orders.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_invoices.id", ondelete="SET NULL")
    )
    receiver_email: Mapped[str] = mapped_column(String(320))
    receiver_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[ReceiptRequestStatus] = mapped_column(string_enum(ReceiptRequestStatus, 16))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime | None]
    nudges: Mapped[int] = mapped_column(default=0)
    last_nudged_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_receipts.id", ondelete="SET NULL")
    )
