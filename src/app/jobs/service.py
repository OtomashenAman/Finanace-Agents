"""Queue health for Finance Admins: what's waiting, what failed, and retrying it."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent
from src.app.agent_catalog.runs.models import AgentRun
from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.jobs.models import Job, JobStatus
from src.app.jobs.schemas import JobOut, KindCounts, QueueSummary

RECENT = 25


class JobNotFoundError(AppError):
    status_code = 404
    code = "job_not_found"
    message = "Job not found."


class JobNotRetryableError(AppError):
    status_code = 409
    code = "job_not_retryable"
    message = "Only failed jobs can be retried."


def _run_id(job: Job) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(job.payload.get("run_id")))
    except ValueError:
        return None


async def _out(session: AsyncSession, jobs: list[Job]) -> list[JobOut]:
    run_ids = {i for j in jobs if (i := _run_id(j)) is not None}
    runs: dict[uuid.UUID, tuple[str, str]] = {}
    if run_ids:
        rows = await session.execute(
            select(AgentRun, Agent.key)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(AgentRun.id.in_(run_ids))
        )
        runs = {run.id: (run.reference, key) for run, key in rows}
    out = []
    for j in jobs:
        run_id = _run_id(j)
        run = runs.get(run_id) if run_id else None
        out.append(
            JobOut(
                id=j.id,
                kind=j.kind,
                status=j.status,
                attempts=j.attempts,
                max_attempts=j.max_attempts,
                last_error=j.last_error,
                payload=j.payload,
                created_at=j.created_at,
                run_after=j.run_after,
                finished_at=j.finished_at,
                run_reference=run[0] if run else None,
                run_link=f"/catalog/{run[1]}/runs/{run_id}" if run else None,
            )
        )
    return out


async def summary(session: AsyncSession) -> QueueSummary:
    now = utcnow()
    counts = await session.execute(
        select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)
    )
    by_kind: dict[str, dict[JobStatus, int]] = {}
    for kind, status, n in counts:
        by_kind.setdefault(kind, {})[status] = n
    total = {s: sum(k.get(s, 0) for k in by_kind.values()) for s in JobStatus}
    oldest = await session.scalar(
        select(func.min(Job.run_after)).where(Job.status == JobStatus.QUEUED, Job.run_after <= now)
    )
    succeeded_24h = await session.scalar(
        select(func.count()).where(
            Job.status == JobStatus.SUCCEEDED, Job.finished_at >= now - timedelta(hours=24)
        )
    )
    failures = list(
        await session.scalars(
            select(Job)
            .where(Job.status == JobStatus.FAILED)
            .order_by(Job.finished_at.desc())
            .limit(RECENT)
        )
    )
    retrying = list(
        await session.scalars(
            select(Job)
            .where(Job.status == JobStatus.QUEUED, Job.last_error.is_not(None))
            .order_by(Job.run_after)
            .limit(RECENT)
        )
    )
    return QueueSummary(
        queued=total[JobStatus.QUEUED],
        running=total[JobStatus.RUNNING],
        failed=total[JobStatus.FAILED],
        succeeded_24h=succeeded_24h or 0,
        oldest_queued_seconds=int((now - oldest).total_seconds()) if oldest else None,
        by_kind=[
            KindCounts(
                kind=kind,
                queued=c.get(JobStatus.QUEUED, 0),
                running=c.get(JobStatus.RUNNING, 0),
                succeeded=c.get(JobStatus.SUCCEEDED, 0),
                failed=c.get(JobStatus.FAILED, 0),
            )
            for kind, c in sorted(by_kind.items())
        ],
        failures=await _out(session, failures),
        retrying=await _out(session, retrying),
    )


async def retry(
    session: AsyncSession, job_id: uuid.UUID, actor: User, ctx: RequestContext
) -> JobOut:
    """Give a failed job a fresh set of attempts, now."""
    job = await session.get(Job, job_id, with_for_update=True)
    if job is None:
        raise JobNotFoundError
    if job.status != JobStatus.FAILED:
        raise JobNotRetryableError
    job.status = JobStatus.QUEUED
    job.max_attempts = job.attempts + 3
    job.run_after = utcnow()
    job.finished_at = None
    record_event(session, "jobs.retried", ctx, actor_id=actor.id, job_id=str(job.id), kind=job.kind)
    await session.commit()
    return (await _out(session, [job]))[0]
