import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
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


class Direction(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class Audience(StrEnum):
    CUSTOMER = "customer"  # only the verified contact from the snapshot
    INTERNAL = "internal"  # only the configured internal recipients


class MessageStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENDING = "sending"
    SENT = "sent"  # the provider accepted it (queued), not proof of inbox delivery
    SEND_FAILED = "send_failed"  # the provider refused it; nothing went out
    SEND_UNKNOWN = "send_unknown"  # outcome unknown: reconcile with the provider log first
    RECEIVED = "received"  # an imported reply


class PodMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An outbound email (draft -> approved -> sent) or an imported customer reply.

    approval_hash binds the exact subject, body, recipient, attachments, purpose and
    transport that were approved; any edit clears it.
    """

    __tablename__ = "pod_messages"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        enum_check("direction", Direction),
        enum_check("status", MessageStatus),
        enum_check("audience", Audience),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[Direction] = mapped_column(string_enum(Direction, 16))
    audience: Mapped[Audience | None] = mapped_column(string_enum(Audience, 16))
    purpose: Mapped[str] = mapped_column(String(50))
    status: Mapped[MessageStatus] = mapped_column(string_enum(MessageStatus, 16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    to_email: Mapped[str] = mapped_column(String(320))
    to_name: Mapped[str | None] = mapped_column(String(200))
    from_email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    artifact_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Verified figures from the source that must appear unchanged in the body
    fact_block: Mapped[str | None] = mapped_column(Text)
    # The reviewer's confirmed checks at approval (recipient, invoice mapping, tone)
    approval_checks: Mapped[dict[str, bool] | None] = mapped_column(JSONB)
    # Replies: what the AI read (output, provenance, problems) and how that went
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    extraction_status: Mapped[str | None] = mapped_column(String(16))  # pending|done|failed|skipped

    approval_hash: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None]
    provider: Mapped[str | None] = mapped_column(String(20))  # transport fixed at approval
    sender: Mapped[str | None] = mapped_column(String(320))
    simulated: Mapped[bool] = mapped_column(default=False)  # outbox: nothing left the app
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(String(500))

    # Threading: our Message-ID on outbound mail, the reply's own on inbound mail
    internet_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pod_messages.id", ondelete="RESTRICT")
    )
    thread_evidence: Mapped[str | None] = mapped_column(String(20))  # "header" | "manual"
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    raw: Mapped[str | None] = mapped_column(Text)  # the reply exactly as imported
    received_at: Mapped[datetime | None]

    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class ArtifactKind(StrEnum):
    TIMESHEET = "timesheet"
    INVOICE_COPY = "invoice_copy"
    MSA = "msa"
    SUPPORTING = "supporting"
    OTHER = "other"


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PodArtifact(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A supporting document (timesheet, invoice copy...) tied to invoices of one case. It
    goes out as an attachment only once approved, and only from its own case."""

    __tablename__ = "pod_artifacts"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("case_id", "sha256"),
        enum_check("kind", ArtifactKind),
        enum_check("status", ArtifactStatus),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ArtifactKind] = mapped_column(string_enum(ArtifactKind, 32))
    invoice_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(150))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    status: Mapped[ArtifactStatus] = mapped_column(
        string_enum(ArtifactStatus, 16), default=ArtifactStatus.PENDING
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None]
