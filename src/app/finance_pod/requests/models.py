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


class RequestStatus(StrEnum):
    DRAFT = "draft"  # the requester is still writing it
    SUBMITTED = "submitted"  # waiting for the budget check and the budget owner (1.2)
    QUERIED = "queried"  # the budget owner asked the requester something; editable again
    APPROVED = "approved"  # budget owner approved: sourcing can start (1.3)
    ORDERED = "ordered"  # its PO is issued (1.6)
    REJECTED = "rejected"
    CANCELLED = "cancelled"


EDITABLE = frozenset({RequestStatus.DRAFT, RequestStatus.QUERIED})


class CodingSource(StrEnum):
    REQUESTER = "requester"  # typed or picked by the requester
    AGENT = "agent"  # the request agent's suggestion, accepted by the requester


class FpPurchaseRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A purchase request (Phase 1.1). `version` grows with every change; a change that
    names an older version is refused instead of overwriting someone's work."""

    __tablename__ = "fpod_requests"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        enum_check("status", RequestStatus),
        enum_check("coding_source", CodingSource),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[RequestStatus] = mapped_column(
        string_enum(RequestStatus, 16), default=RequestStatus.DRAFT, index=True
    )
    version: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text, default="")
    needed_by: Mapped[date | None]
    currency: Mapped[str] = mapped_column(String(3))
    cost_centre_code: Mapped[str | None] = mapped_column(String(40))
    lab_code: Mapped[str | None] = mapped_column(String(40))
    project_code: Mapped[str | None] = mapped_column(String(40))
    grant_code: Mapped[str | None] = mapped_column(String(40))
    coding_source: Mapped[CodingSource | None] = mapped_column(string_enum(CodingSource, 16))
    # How it was described: the form, or free text the agent turned into the form
    source_text: Mapped[str | None] = mapped_column(Text)
    # The request agent's last run: coding suggestion, price checks, missing data
    enrichment: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Each submission is a round; decisions of earlier rounds stay as history
    round: Mapped[int] = mapped_column(default=0, server_default="0")
    # The budget agent's check of the current round: impact, grant rules, approval route
    budget_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None]
    approved_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]

    lines: Mapped[list["FpRequestLine"]] = relationship(
        order_by="FpRequestLine.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def reference(self) -> str:
        return f"PR-{self.number:04d}"

    @property
    def total(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal("0.00"))


class FpRequestLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fpod_request_lines"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))  # the estimate
    category: Mapped[str | None] = mapped_column(String(64))
    catalogue_item_code: Mapped[str | None] = mapped_column(String(40))

    @property
    def amount(self) -> Decimal:
        if self.unit_price is None:
            return Decimal("0.00")
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))


class RequestFileKind(StrEnum):
    QUOTE = "quote"
    SPECIFICATION = "specification"
    OTHER = "other"


class FpRequestFile(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A quote or other document the requester attached."""

    __tablename__ = "fpod_request_files"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("request_id", "sha256"),
        enum_check("kind", RequestFileKind),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[RequestFileKind] = mapped_column(string_enum(RequestFileKind, 16))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(150))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
