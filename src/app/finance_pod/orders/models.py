import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.common.models import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class PoStatus(StrEnum):
    DRAFT = "draft"  # the PO agent drafted it; the buyer checks it
    PENDING_APPROVAL = "pending_approval"  # above the buyer's limit: waits for approval
    APPROVED = "approved"  # ready to issue
    ISSUED = "issued"  # created in the ERP and sent to the vendor
    ACKNOWLEDGED = "acknowledged"  # the vendor confirmed it
    CANCELLED = "cancelled"


class FpPurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A purchase order (Phase 1.6). Guardrail: it always comes from an approved request
    (request_id is required, one live PO per request, and a database trigger refuses a PO
    for a request that isn't approved)."""

    __tablename__ = "fpod_purchase_orders"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        enum_check("status", PoStatus),
        # One live PO per request (a cancelled one may be redrafted)
        Index(
            "uq_fpod_purchase_orders_live_request",
            "request_id",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[PoStatus] = mapped_column(string_enum(PoStatus, 24), index=True)
    version: Mapped[int] = mapped_column(default=1)
    vendor_code: Mapped[str] = mapped_column(String(40))
    vendor_name: Mapped[str] = mapped_column(String(200))
    vendor_email: Mapped[str | None] = mapped_column(String(320))
    currency: Mapped[str] = mapped_column(String(3))
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    delivery_date: Mapped[date | None]
    cost_centre_code: Mapped[str | None] = mapped_column(String(40))
    lab_code: Mapped[str | None] = mapped_column(String(40))
    project_code: Mapped[str | None] = mapped_column(String(40))
    grant_code: Mapped[str | None] = mapped_column(String(40))
    quote_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # the chosen quote's
    notes: Mapped[str | None] = mapped_column(Text)
    drafted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Above the limit (authority matrix, scope "po"): who must approve (1.6.2.a)
    approval_capacity: Mapped[str | None] = mapped_column(String(60))
    approver_email: Mapped[str | None] = mapped_column(String(320))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None]
    approval_acting_for: Mapped[str | None] = mapped_column(String(320))
    self_approval: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    issued_at: Mapped[datetime | None]
    erp_system: Mapped[str | None] = mapped_column(String(20))
    erp_ref: Mapped[str | None] = mapped_column(String(100))
    acknowledged_at: Mapped[datetime | None]
    acknowledgement_note: Mapped[str | None] = mapped_column(Text)
    acknowledgement_filename: Mapped[str | None] = mapped_column(String(255))
    acknowledgement_content_type: Mapped[str | None] = mapped_column(String(150))
    acknowledgement_file: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["FpPoLine"]] = relationship(
        order_by="FpPoLine.position", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def reference(self) -> str:
        return f"PO-{self.number:05d}"

    @property
    def total(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal("0.00"))


class FpPoLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fpod_po_lines"

    po_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_purchase_orders.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    category: Mapped[str | None] = mapped_column(String(64))
    catalogue_item_code: Mapped[str | None] = mapped_column(String(40))
    price_source: Mapped[str] = mapped_column(String(20))  # contract / quote / estimate / buyer

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))
