import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Append-only audit trail (auth events now; run/review events later)."""

    __tablename__ = "audit_events"

    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
