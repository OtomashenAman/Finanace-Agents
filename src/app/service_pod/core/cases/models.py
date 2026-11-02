import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Numeric, String, Text
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
from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey


class CaseStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"  # back to draft when its content changes
    COMPLETED = "completed"
    CANCELLED = "cancelled"


LOCKED_STATUSES = frozenset({CaseStatus.COMPLETED, CaseStatus.CANCELLED})


class PodCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One piece of governed work on one snapshot. `version` grows with every change; a
    request that names an older version is refused instead of overwriting someone's work."""

    __tablename__ = "pod_cases"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        enum_check("workflow", WorkflowKey),
        enum_check("status", CaseStatus),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    workflow: Mapped[WorkflowKey] = mapped_column(string_enum(WorkflowKey, 32), index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_snapshots.id", ondelete="RESTRICT")
    )
    snapshot_sha: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[CaseStatus] = mapped_column(string_enum(CaseStatus, 32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    completed_at: Mapped[datetime | None]

    @property
    def reference(self) -> str:
        return f"{WORKFLOWS[self.workflow].prefix}-{self.number:04d}"


class PodApproval(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """The case's content as it was approved: valid only while the case's fingerprint still
    equals content_hash. Rows are never changed; history stays."""

    __tablename__ = "pod_approvals"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    content_hash: Mapped[str] = mapped_column(String(64))
    # The capacity the sign-off was given in, e.g. "Finance Head" (WorkflowSpec.signoff_as)
    capacity: Mapped[str] = mapped_column(String(50), default="Finance Admin")


class ReviewTaskKind(StrEnum):
    UNKNOWN_DATE = "unknown_date"
    DISPUTE = "dispute"
    MISSING_DOCUMENT = "missing_document"
    AMBIGUITY = "ambiguity"
    SCOPE = "scope"  # e.g. aging as-of date differs from the report month
    OTHER = "other"


class ReviewTaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class PodReviewTask(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Something a person must settle before the case can be approved: never assumed away."""

    __tablename__ = "pod_review_tasks"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("kind", ReviewTaskKind), enum_check("status", ReviewTaskStatus))

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ReviewTaskKind] = mapped_column(string_enum(ReviewTaskKind, 32))
    subject: Mapped[str | None] = mapped_column(String(200))  # e.g. an invoice number
    detail: Mapped[str] = mapped_column(Text)
    blocking: Mapped[bool] = mapped_column(default=True)
    # What settles it, when a person's note isn't enough, e.g. {"type": "customer_date",
    # "commitment_id": ...} (only a customer reply) or {"type": "document", "kind": "timesheet",
    # "invoice": "INV-101"} (an approved document of that kind for that invoice)
    requirement: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[ReviewTaskStatus] = mapped_column(
        string_enum(ReviewTaskStatus, 16), default=ReviewTaskStatus.OPEN
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(  # None: raised by the system / AI
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None]


class ActionStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class PodOwnedAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A follow-up with a responsible person, a due date and an outcome (FP&A action
    register, treasury mitigation, reporting follow-ups)."""

    __tablename__ = "pod_owned_actions"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", ActionStatus),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    due_date: Mapped[date]
    status: Mapped[ActionStatus] = mapped_column(
        string_enum(ActionStatus, 16), default=ActionStatus.OPEN
    )
    outcome: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class CommitmentStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class PodCommitment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A customer's promise to pay part of an invoice. Never a receipt: it changes no
    balance, and treasury reads approved ones as expected (not actual) cash."""

    __tablename__ = "pod_commitments"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("status", CommitmentStatus),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[str] = mapped_column(String(100))
    invoice_number: Mapped[str] = mapped_column(String(100), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    expected_date: Mapped[date | None]  # None: the customer didn't say (needs a review task)
    probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal(1))
    probability_rationale: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)  # the customer's words it came from
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pod_messages.id", ondelete="RESTRICT")
    )
    status: Mapped[CommitmentStatus] = mapped_column(
        string_enum(CommitmentStatus, 16), default=CommitmentStatus.PROPOSED
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None]
