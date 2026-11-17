"""E-signature: templates a person uploads, and the documents they send through PandaDoc.

Everything here is its sender's own: nobody else (a Finance Admin included) sees another
person's templates, documents or their statuses.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from src.app.common.models import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class EsignTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A PDF / Word / RTF file, kept so it can be sent again and again. PandaDoc keeps
    nothing between sends, so the file is uploaded with every document made from it."""

    __tablename__ = "esign_templates"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Where signers sign: {"page", "x", "y", "width", "height"} (points from the page's
    # top-left corner) for a signature box placed there, or None when the file carries
    # PandaDoc field tags ({signature:signer1___}) instead
    signature_layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The PandaDoc field tags found in the file: [{"type", "role", "id", "required",
    # "prefillable"}]. Those with an id (text, date, checkbox) are filled in when sending
    field_tags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    # The file itself; deferred so listing templates never loads it
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary))


class EsignDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One document sent (or being sent) for signature. `status` is PandaDoc's
    (document.sent, document.completed, ...), or ours before PandaDoc has one: "failed"."""

    __tablename__ = "esign_documents"
    __table_args__ = (Index("ix_esign_documents_sender_created", "sender_id", "created_at"),)

    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("esign_templates.id", ondelete="SET NULL"), index=True
    )
    template_name: Mapped[str] = mapped_column(String(200))  # kept if the template goes
    pandadoc_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(48))
    # Sent once PandaDoc has prepared the document (a few seconds after the upload)
    send_pending: Mapped[bool] = mapped_column(default=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str | None] = mapped_column(Text)
    # The template's signature_layout when it was sent (boxes are added once PandaDoc has
    # prepared the document, before it is sent)
    signature_layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The values filled into the template's dynamic fields when sending ({id: value})
    field_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # [{"email", "name", "role", "has_completed", "completed_at"}]
    recipients: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]
    viewed_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    status_changed_at: Mapped[datetime | None]


class EsignEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """What happened to a document (from PandaDoc's webhooks, a refresh, or the app)."""

    __tablename__ = "esign_events"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("esign_documents.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(48))
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    # X-PandaDoc-Webhook-Event-Id: a delivery PandaDoc retries is only applied once
    delivery_id: Mapped[str | None] = mapped_column(String(100), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, default=0)  # order within one delivery
