import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    QUERY = "query"  # a question back to the requester; they edit and resubmit


class FpDecision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One approver's decision on one step of a request's approval route (1.2.2). Never
    changed: a resubmission starts a new round and the old decisions stay as history."""

    __tablename__ = "fpod_decisions"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("decision", Decision),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), index=True
    )
    round: Mapped[int]
    step: Mapped[int]  # 1-based position in the route
    capacity: Mapped[str] = mapped_column(String(60))  # e.g. "Budget owner", "Dean"
    approver_email: Mapped[str | None] = mapped_column(String(320))  # who the route named
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision: Mapped[Decision] = mapped_column(string_enum(Decision, 16))
    note: Mapped[str] = mapped_column(Text, default="")
    # The named approver has no account, so another Finance Admin decided for them
    acting_for: Mapped[str | None] = mapped_column(String(320))
    # Approved although over budget / without a budget line (the note says why)
    budget_acknowledged: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # The requester decided their own request (only with self-approval allowed)
    self_approval: Mapped[bool] = mapped_column(default=False, server_default=text("false"))


class FpCommitment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Budget an approved request holds until it becomes a PO (or is cancelled). Counted
    against the budget line by the budget agent on later requests."""

    __tablename__ = "fpod_commitments"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), index=True
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fpod_budgets.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    released_at: Mapped[datetime | None]
    release_reason: Mapped[str | None] = mapped_column(String(200))
