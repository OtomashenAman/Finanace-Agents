"""Scheduled audit upkeep, run by the worker."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit import integrity
from src.app.jobs.queue import JobContext, daily, handler

PURGE_JOB = "audit.purge"


@daily(PURGE_JOB)
@handler(PURGE_JOB)
async def purge_expired(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    """Remove events past AUDIT_RETENTION_DAYS (the purge records itself in the trail)."""
    await integrity.purge(session)
