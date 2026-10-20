import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only audit trail: sign-ins, user management, runs and reviews, data sources.

    Never updated or deleted. details never holds passwords, secrets or tokens.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        # Newest-first listing with keyset pagination
        Index("ix_audit_events_created_at_id", "created_at", "id"),
        # A run's timeline and "events about this user" look inside details
        Index("ix_audit_events_run", text("(details ->> 'run')")),
        Index("ix_audit_events_subject_user", text("(details ->> 'user_id')")),
    )

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
