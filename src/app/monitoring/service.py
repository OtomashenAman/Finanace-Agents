"""AI (LLM) call monitoring for Finance Admins, computed from run_narratives on every request.

Every narrative row is one model call: what was sent, what came back, tokens, latency and the
guard's notes. Nothing here changes data.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Date, Select, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent
from src.app.agent_catalog.runs.models import AgentRun, NarrativeStatus, RunNarrative
from src.app.common.clock import utcnow
from src.app.monitoring.schemas import (
    LlmBreakdown,
    LlmCall,
    LlmCallRun,
    LlmDay,
    LlmSummary,
    LlmTotals,
)

RECENT = 20


def _ms(value: Any) -> int | None:
    return round(value) if value is not None else None


def _aggregates() -> tuple[Any, ...]:
    return (
        func.count(),
        func.count().filter(RunNarrative.status == NarrativeStatus.FAILED),
        func.coalesce(func.sum(RunNarrative.input_tokens), 0),
        func.coalesce(func.sum(RunNarrative.output_tokens), 0),
        func.avg(RunNarrative.latency_ms),
    )


def _calls(since: datetime) -> Select[RunNarrative, AgentRun, Agent]:
    return (
        select(RunNarrative, AgentRun, Agent)
        .join(AgentRun, AgentRun.id == RunNarrative.run_id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(RunNarrative.created_at >= since)
        .order_by(RunNarrative.created_at.desc())
    )


def _call_out(narrative: RunNarrative, run: AgentRun, agent: Agent) -> LlmCall:
    return LlmCall(
        id=narrative.id,
        created_at=narrative.created_at,
        status=narrative.status,
        provider=narrative.provider,
        model=narrative.model,
        prompt_version=narrative.prompt_version,
        run=LlmCallRun(
            id=run.id, reference=run.reference, agent_key=agent.key, agent_name=agent.short_name
        ),
        input_tokens=narrative.input_tokens,
        output_tokens=narrative.output_tokens,
        latency_ms=narrative.latency_ms,
        guard_warnings=narrative.guard_warnings,
        error=narrative.error,
    )


async def health_line(session: AsyncSession) -> str:
    """For the admin overview, e.g. "Guarded · 42 calls, 2% failed (7 days)"."""
    since = utcnow() - timedelta(days=7)
    calls, failed = (
        await session.execute(
            select(
                func.count(), func.count().filter(RunNarrative.status == NarrativeStatus.FAILED)
            ).where(RunNarrative.created_at >= since)
        )
    ).one()
    if not calls:
        return "Guarded · no calls in 7 days"
    return f"Guarded · {calls} calls, {failed / calls:.0%} failed (7 days)"


async def summary(session: AsyncSession, days: int) -> LlmSummary:
    now = utcnow()
    today = now.astimezone(UTC).date()
    first_day = today - timedelta(days=days - 1)
    since = datetime.combine(first_day, datetime.min.time(), UTC)
    in_window = RunNarrative.created_at >= since
    p95 = func.percentile_cont(0.95).within_group(RunNarrative.latency_ms)

    row = (
        await session.execute(
            select(
                *_aggregates(),
                func.count().filter(RunNarrative.status == NarrativeStatus.OK),
                func.count().filter(RunNarrative.status == NarrativeStatus.NOT_CONFIGURED),
                func.count().filter(func.jsonb_array_length(RunNarrative.guard_warnings) > 0),
                func.coalesce(func.sum(RunNarrative.cached_tokens), 0),
                p95,
            ).where(in_window)
        )
    ).one()
    (
        calls,
        failed,
        tokens_in,
        tokens_out,
        avg_latency,
        ok,
        not_configured,
        warned,
        cached,
        p95_ms,
    ) = row
    totals = LlmTotals(
        calls=calls,
        ok=ok,
        failed=failed,
        not_configured=not_configured,
        failure_rate=failed / calls if calls else 0.0,
        with_guard_warnings=warned,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cached_tokens=cached,
        avg_latency_ms=_ms(avg_latency),
        p95_latency_ms=_ms(p95_ms),
    )

    day = cast(func.timezone("UTC", RunNarrative.created_at), Date)
    per_day = {
        d: (n, f, i, o, p)
        for d, n, f, i, o, _avg, p in await session.execute(
            select(day, *_aggregates(), p95).where(in_window).group_by(day)
        )
    }
    daily = []
    for offset in range(days):
        d = first_day + timedelta(days=offset)
        n, f, i, o, p = per_day.get(d, (0, 0, 0, 0, None))
        daily.append(
            LlmDay(day=d, calls=n, failed=f, input_tokens=i, output_tokens=o, p95_latency_ms=_ms(p))
        )

    by_model = [
        LlmBreakdown(
            key=model,
            label=f"{model} ({provider})",
            calls=n,
            failed=f,
            input_tokens=i,
            output_tokens=o,
            avg_latency_ms=_ms(a),
        )
        for model, provider, n, f, i, o, a in await session.execute(
            select(RunNarrative.model, RunNarrative.provider, *_aggregates())
            .where(in_window)
            .group_by(RunNarrative.model, RunNarrative.provider)
            .order_by(func.count().desc())
        )
    ]
    by_agent = [
        LlmBreakdown(
            key=key,
            label=name,
            calls=n,
            failed=f,
            input_tokens=i,
            output_tokens=o,
            avg_latency_ms=_ms(a),
        )
        for key, name, n, f, i, o, a in await session.execute(
            select(Agent.key, Agent.short_name, *_aggregates())
            .select_from(RunNarrative)
            .join(AgentRun, AgentRun.id == RunNarrative.run_id)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(in_window)
            .group_by(Agent.key, Agent.short_name)
            .order_by(func.count().desc())
        )
    ]

    problems = case((RunNarrative.status == NarrativeStatus.OK, 0), else_=1)
    failures = await session.execute(_calls(since).where(problems == 1).limit(RECENT))
    recent = await session.execute(_calls(since).limit(RECENT))
    return LlmSummary(
        days=days,
        since=since,
        totals=totals,
        daily=daily,
        by_model=by_model,
        by_agent=by_agent,
        recent_failures=[_call_out(n, run, agent) for n, run, agent in failures],
        recent_calls=[_call_out(n, run, agent) for n, run, agent in recent],
    )
