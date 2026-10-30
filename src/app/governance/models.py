import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

SETTINGS_ROW = 1


class OrgSettings(TimestampMixin, Base):
    """Organization-wide controls (a single row)."""

    __tablename__ = "org_settings"
    __table_args__ = (CheckConstraint(f"id = {SETTINGS_ROW}", name="single_row"),)
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    id: Mapped[int] = mapped_column(primary_key=True, default=SETTINGS_ROW)
    # Maker-checker: off means nobody, not even a Finance Admin, approves their own run
    allow_admin_self_approval: Mapped[bool] = mapped_column(
        default=True, server_default=text("true")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AgentPolicy(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One version of an agent's thresholds. Never updated: a change is a new version.

    Without any row the agent runs on its code defaults (its `policy_version`, e.g. v1).
    """

    __tablename__ = "agent_policies"
    __table_args__ = (UniqueConstraint("agent_key", "version"),)

    agent_key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int]
    values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class ApprovalRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Approval matrix tier: from `min_amount` up, how many approvals and by whom.

    Without rules an agent's runs need one approval from any Finance Admin.
    """

    __tablename__ = "approval_rules"
    __table_args__ = (
        UniqueConstraint("agent_key", "min_amount"),
        CheckConstraint("approvals_required BETWEEN 1 AND 3", name="approvals_required"),
        CheckConstraint("min_amount >= 0", name="min_amount"),
    )

    agent_key: Mapped[str] = mapped_column(String(64), index=True)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    approvals_required: Mapped[int]
    # Finance Admin user ids allowed to approve this tier; empty = any Finance Admin
    approver_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)


class ApprovalDelegation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """While active, `delegate` may approve wherever the matrix names `delegator` (e.g. leave).

    Reviews given this way record whom they were on behalf of.
    """

    __tablename__ = "approval_delegations"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="period"),
        CheckConstraint("delegator_id <> delegate_id", name="distinct_people"),
    )

    delegator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    delegate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None]
