"""A small Postgres-backed job queue.

- enqueue() is idempotent through `dedupe_key` (INSERT ... ON CONFLICT DO NOTHING).
- Workers claim with FOR UPDATE SKIP LOCKED, so several can run side by side.
- A failing job is retried with exponential backoff, then marked failed for a person to see.
- A job whose worker died (running too long) is put back in the queue.
"""

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.core.llm.base import LLMProvider
from src.app.jobs.models import Job, JobStatus

log = logging.getLogger("finance_acc.jobs")


@dataclass(frozen=True)
class JobContext:
    llm: LLMProvider
    attempt: int  # 1-based
    max_attempts: int

    @property
    def final_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


class RetryLater(Exception):
    """Raised by a handler that wants another attempt (e.g. a transient provider error)."""


Handler = Callable[[AsyncSession, dict[str, Any], JobContext], Awaitable[None]]
_HANDLERS: dict[str, Handler] = {}
_DAILY: list[str] = []  # kinds the worker queues once a day (e.g. the audit retention purge)


def handler(kind: str) -> Callable[[Handler], Handler]:
    """Register the function that runs jobs of `kind`. Handlers don't commit."""

    def register(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return register


def daily(kind: str) -> Callable[[Handler], Handler]:
    """Also run this handler once a day (queued by the workers; the date makes it unique)."""

    def register(fn: Handler) -> Handler:
        _DAILY.append(kind)
        return fn

    return register


async def schedule_daily(session: AsyncSession) -> int:
    """Queue today's run of each daily job unless already queued (commits). Returns how many."""
    today = utcnow().date().isoformat()
    queued = 0
    for kind in _DAILY:
        if await enqueue(session, kind, {"date": today}, dedupe_key=f"{kind}:{today}"):
            queued += 1
    await session.commit()
    return queued


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(10 * 4 ** (attempt - 1), 600))  # 10s, 40s, 160s, 600s


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
) -> Job | None:
    """Queue work (caller commits). None when the same dedupe_key was queued before."""
    if kind not in _HANDLERS:
        raise ValueError(f"No handler registered for job kind {kind!r}")
    result = await session.execute(
        insert(Job)
        .values(
            kind=kind,
            payload=payload,
            dedupe_key=dedupe_key,
            status=JobStatus.QUEUED,
            max_attempts=max_attempts,
        )
        .on_conflict_do_nothing(index_elements=[Job.dedupe_key])
        .returning(Job.id)
    )
    job_id = result.scalar_one_or_none()
    return await session.get(Job, job_id) if job_id else None


async def _run(session: AsyncSession, job: Job, llm: LLMProvider, *, attempt: int) -> None:
    """Run a claimed job and record the outcome (commits)."""
    job_id = job.id
    fn = _HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise RuntimeError(f"No handler for job kind {job.kind!r}")
        await fn(session, job.payload, JobContext(llm, attempt, job.max_attempts))
    except Exception as exc:
        await session.rollback()
        job = await session.get(Job, job_id, with_for_update=True)  # type: ignore[assignment]
        job.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        job.locked_at = job.locked_by = None
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.finished_at = utcnow()
            log.warning("job %s (%s) failed for good: %s", job_id, job.kind, job.last_error)
        else:
            job.status = JobStatus.QUEUED
            job.run_after = utcnow() + backoff(job.attempts)
            log.info("job %s (%s) will retry: %s", job_id, job.kind, job.last_error)
    else:
        job.status = JobStatus.SUCCEEDED
        job.finished_at = utcnow()
        job.locked_at = job.locked_by = None
        job.last_error = None
    await session.commit()


async def run_now(session: AsyncSession, job: Job, llm: LLMProvider) -> None:
    """Inline mode: run a just-queued job in this request, once (no waiting for retries)."""
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.max_attempts = job.attempts  # one shot: the handler treats it as the final attempt
    await session.commit()
    await _run(session, job, llm, attempt=job.attempts)


async def dispatch(session: AsyncSession, job: Job | None, llm: LLMProvider) -> None:
    """After queueing (and committing): run inline when configured, else leave to a worker."""
    if job is not None and get_settings().jobs_mode == "inline":
        await run_now(session, job, llm)


async def claim(session: AsyncSession, worker: str) -> Job | None:
    """Take the next due job, if any (commits)."""
    job = await session.scalar(
        select(Job)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= utcnow())
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is not None:
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_at = utcnow()
        job.locked_by = worker
    await session.commit()
    return job


async def recover_stale(session: AsyncSession) -> int:
    """Requeue jobs whose worker vanished mid-run (commits). Returns how many."""
    cutoff = utcnow() - timedelta(seconds=get_settings().jobs_lock_timeout_seconds)
    result = await session.execute(
        update(Job)
        .where(Job.status == JobStatus.RUNNING, Job.locked_at < cutoff)
        .values(status=JobStatus.QUEUED, locked_at=None, locked_by=None, run_after=utcnow())
        .returning(Job.id)
    )
    recovered = len(result.all())
    await session.commit()
    return recovered


async def work_once(session: AsyncSession, worker: str, llm: LLMProvider) -> bool:
    """Claim and run one job. False when nothing was due."""
    job = await claim(session, worker)
    if job is None:
        return False
    await _run(session, job, llm, attempt=job.attempts)
    return True


async def run_worker(
    sessionmaker: async_sessionmaker[AsyncSession], llm: LLMProvider, stop: asyncio.Event
) -> None:
    """Poll for jobs until `stop` is set. Every minute: requeue stale jobs, queue daily ones."""
    worker = f"{socket.gethostname()}:{os.getpid()}"
    poll = get_settings().jobs_poll_seconds
    last_recovery = 0.0
    log.info("worker %s started", worker)
    while not stop.is_set():
        loop_time = asyncio.get_running_loop().time()
        async with sessionmaker() as session:
            if loop_time - last_recovery > 60:
                if recovered := await recover_stale(session):
                    log.warning("requeued %d stale job(s)", recovered)
                if scheduled := await schedule_daily(session):
                    log.info("queued %d daily job(s)", scheduled)
                last_recovery = loop_time
            busy = await work_once(session, worker, llm)
        if not busy:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=poll)
    log.info("worker %s stopped", worker)
