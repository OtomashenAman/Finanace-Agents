import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class AgentCapacity(StrEnum):
    PREPARER = "preparer"
    REVIEWER = "reviewer"


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Catalog entry for a registered agent.

    Descriptive columns are owned by the code registry and overwritten by `sync-agents`;
    is_active and assignments are owned by admins and never touched by the sync.
    """

    __tablename__ = "agents"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    key: Mapped[str] = mapped_column(String(64), unique=True)
    code: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    primary_user: Mapped[str] = mapped_column(String(100))
    reviewer: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # Set when the agent disappears from the registry; the row stays for runs/audit history
    retired_at: Mapped[datetime | None]


class AgentAssignment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Which user may prepare or review runs of which agent."""

    __tablename__ = "agent_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "agent_id", "capacity"),
        enum_check("capacity", AgentCapacity),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    capacity: Mapped[AgentCapacity] = mapped_column(string_enum(AgentCapacity, 16))
