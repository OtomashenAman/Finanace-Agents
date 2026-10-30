import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    case,
    cast,
    func,
    literal,
    text,
)
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
from src.app.data_sources import models as _data_source_models  # noqa: F401 - FK target
from src.app.entities import models as _entity_models  # noqa: F401 - FK target


class RunStatus(StrEnum):
    DRAFT = "draft"
    VALIDATION_FAILED = "validation_failed"
    ANALYZED = "analyzed"
    PENDING_APPROVAL = "pending_approval"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class RunPriority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"


class FlagSeverity(StrEnum):
    PASS = "pass"  # noqa: S105 - control checked and satisfied, not a password
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"  # exception the reviewer must resolve


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class NarrativeStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lifecycle of one analysis, common to every agent.

    The agent's own fields live in its table (e.g. ap_invoice_runs), linked 1:1 by run_id.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        enum_check("status", RunStatus),
        enum_check("priority", RunPriority),
        Index("ix_agent_runs_agent_id_status", "agent_id", "status"),
        UniqueConstraint("preparer_id", "idempotency_key", name="uq_agent_runs_idempotency_key"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    run_number: Mapped[int] = mapped_column(BigInteger, Identity(start=1001), unique=True)
    # Client-chosen key for "create run": a retried request returns the same run
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), index=True
    )
    preparer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # Legal entity the run is filed for; None for runs from before entities were set up
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[RunStatus] = mapped_column(string_enum(RunStatus, 32), default=RunStatus.DRAFT)
    priority: Mapped[RunPriority] = mapped_column(
        string_enum(RunPriority, 16), default=RunPriority.NORMAL
    )
    policy_version: Mapped[str | None] = mapped_column(String(50))
    # The threshold values the analysis used (with policy_version: what exactly applied)
    policy_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Fixed on submit from the approval matrix: approvals needed and the matched tier
    required_approvals: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    approval_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    headline: Mapped[str | None] = mapped_column(String(200))
    proposed_decision: Mapped[str | None] = mapped_column(String(300))
    # Display snapshot of the engine's figures; the typed values live in the agent table
    calculations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    validation_errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    analyzed_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]
    decided_at: Mapped[datetime | None]

    @property
    def reference(self) -> str:
        return f"RUN-{self.run_number:05d}"

    @classmethod
    def reference_sql(cls) -> ColumnElement[str]:
        """`reference` in SQL (audit events store it), e.g. to match a user's runs."""
        number = cast(cls.run_number, String)
        padded = case((cls.run_number < 100_000, func.lpad(number, 5, "0")), else_=number)
        return literal("RUN-") + padded


class AgentRunDetail:
    """Mixin for an agent's own run table: one row per run, keyed by run_id."""

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )


class RunFlag(UUIDPrimaryKeyMixin, Base):
    """Findings from the deterministic engine (passes and exceptions)."""

    __tablename__ = "run_flags"
    __table_args__ = (enum_check("severity", FlagSeverity),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[FlagSeverity] = mapped_column(string_enum(FlagSeverity, 16))
    message: Mapped[str] = mapped_column(String(500))
    field: Mapped[str | None] = mapped_column(String(64))


class RunDocument(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Text extracted from an uploaded file. The file itself is never stored."""

    __tablename__ = "run_documents"
    __table_args__ = (UniqueConstraint("run_id", "sha256"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))  # proves which file the text came from
    extractor: Mapped[str] = mapped_column(String(32))
    page_count: Mapped[int | None]
    char_count: Mapped[int]
    truncated: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    extracted_text: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class RunNarrative(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One LLM call: exactly what was sent, what came back, and how it was checked."""

    __tablename__ = "run_narratives"
    __table_args__ = (enum_check("status", NarrativeStatus),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[NarrativeStatus] = mapped_column(string_enum(NarrativeStatus, 16))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    guard_warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cached_tokens: Mapped[int | None]
    latency_ms: Mapped[int | None]


class RunReview(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A reviewer decision. Never updated or deleted."""

    __tablename__ = "run_reviews"
    __table_args__ = (enum_check("decision", ReviewDecision),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Approved as a delegate of this approver (approval matrix + delegation)
    on_behalf_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decision: Mapped[ReviewDecision] = mapped_column(string_enum(ReviewDecision, 32))
    comment: Mapped[str] = mapped_column(Text)
    result_hash: Mapped[str] = mapped_column(String(64))  # what exactly was approved


class RunSourceSnapshot(CreatedAtMixin, Base):
    """The data source records a run was prefilled from, frozen at that moment.

    Reviewers see this, not the preparer's live source (which they can't access and which may
    have changed since). Kept when the source is deleted.
    """

    __tablename__ = "run_source_snapshots"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(32))
    source_name: Mapped[str] = mapped_column(String(200))
    record_type: Mapped[str] = mapped_column(String(32))
    record_reference: Mapped[str] = mapped_column(String(200))
    # {"bill": {...}, "purchase_order": {...}}: the selected record and what it pulled in
    records: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_synced_at: Mapped[datetime | None]


class ActionStatus(StrEnum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExternalAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A write to an outside system after approval, with its receipt (one per kind per run).

    Never automatic: a person asks for it, a background job performs it.
    """

    __tablename__ = "run_actions"
    __table_args__ = (UniqueConstraint("run_id", "kind"), enum_check("status", ActionStatus))
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64))  # e.g. "quickbooks.bill_approval_note"
    status: Mapped[ActionStatus] = mapped_column(string_enum(ActionStatus, 16))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # What the outside system confirmed (ids, versions, the text written)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None]
