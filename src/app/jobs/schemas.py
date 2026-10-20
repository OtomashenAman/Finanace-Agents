import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.app.jobs.models import JobStatus


class KindCounts(BaseModel):
    kind: str
    queued: int
    running: int
    succeeded: int
    failed: int


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: JobStatus
    attempts: int
    max_attempts: int
    last_error: str | None
    payload: dict[str, Any]
    created_at: datetime
    run_after: datetime
    finished_at: datetime | None
    # Where it came from, when it's about a run (for a link)
    run_reference: str | None
    run_link: str | None


class QueueSummary(BaseModel):
    queued: int
    running: int
    failed: int
    succeeded_24h: int
    oldest_queued_seconds: int | None  # how long the longest-waiting due job has waited
    by_kind: list[KindCounts]
    failures: list[JobOut]  # failed for good, newest first
    retrying: list[JobOut]  # queued again after an error
