"""Business health as Prometheus gauges, read from the database at scrape time.

Unlike the HTTP counters these are the same whichever process answers the scrape.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.runs.models import AgentRun, NarrativeStatus, RunNarrative, RunStatus
from src.app.audit.models import AuditEvent
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.core.observability import gauge
from src.app.data_sources.models import DataSource, SourceStatus
from src.app.jobs.models import Job, JobStatus


async def business_metrics(session: AsyncSession) -> list[str]:
    now = utcnow()
    jobs = dict(
        (await session.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    )
    oldest = await session.scalar(
        select(func.min(Job.run_after)).where(Job.status == JobStatus.QUEUED, Job.run_after <= now)
    )
    llm = dict(
        (
            await session.execute(
                select(RunNarrative.status, func.count())
                .where(RunNarrative.created_at >= now - timedelta(hours=24))
                .group_by(RunNarrative.status)
            )
        ).all()
    )
    sla = timedelta(hours=get_settings().review_sla_hours)
    pending = await session.scalar(
        select(func.count()).where(AgentRun.status == RunStatus.PENDING_APPROVAL)
    )
    overdue = await session.scalar(
        select(func.count()).where(
            AgentRun.status == RunStatus.PENDING_APPROVAL, AgentRun.submitted_at < now - sla
        )
    )
    locked = await session.scalar(select(func.count()).where(User.locked_until > now))
    sources = dict(
        (
            await session.execute(
                select(DataSource.status, func.count()).group_by(DataSource.status)
            )
        ).all()
    )
    audit_seq = await session.scalar(select(func.max(AuditEvent.seq)))

    return [
        *gauge(
            "finance_acc_jobs",
            "Background jobs by status.",
            [({"status": s.value}, jobs.get(s, 0)) for s in JobStatus],
        ),
        *gauge(
            "finance_acc_jobs_oldest_queued_seconds",
            "How long the longest-waiting due job has waited (0: none waiting).",
            [({}, (now - oldest).total_seconds() if oldest else 0)],
        ),
        *gauge(
            "finance_acc_llm_calls_24h",
            "AI explanation calls in the last 24 hours by outcome.",
            [({"status": s.value}, llm.get(s, 0)) for s in NarrativeStatus],
        ),
        *gauge(
            "finance_acc_runs_pending_approval", "Runs waiting for approval.", [({}, pending or 0)]
        ),
        *gauge(
            "finance_acc_runs_overdue_approval",
            "Runs waiting for approval longer than the review SLA.",
            [({}, overdue or 0)],
        ),
        *gauge(
            "finance_acc_locked_accounts",
            "Accounts locked by failed sign-ins.",
            [({}, locked or 0)],
        ),
        *gauge(
            "finance_acc_data_sources",
            "Data sources by status.",
            [({"status": s.value}, sources.get(s, 0)) for s in SourceStatus],
        ),
        *gauge(
            "finance_acc_audit_events_last_seq",
            "Sequence number of the newest audit event (should only grow).",
            [({}, audit_seq or 0)],
        ),
    ]
