from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # gave up after max_attempts (needs a person: retry or ignore)


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A unit of background work (e.g. drafting a run's AI explanation).

    Workers claim rows with SELECT ... FOR UPDATE SKIP LOCKED, so any number can run.
    `dedupe_key` makes enqueueing idempotent: the same work is never queued twice.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("status", JobStatus),
        Index("ix_jobs_claim", "status", "run_after"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    status: Mapped[JobStatus] = mapped_column(string_enum(JobStatus, 16), default=JobStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(default=3, server_default=text("3"))
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    locked_at: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    finished_at: Mapped[datetime | None]
