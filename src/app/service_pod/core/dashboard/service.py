"""The Service POD dashboard: counts across every case, for the Finance Admin's overview.
Workflow figures (AR balance, unapplied cash) come from each workflow's own screen; this
module only counts what every workflow shares: cases, promises, mail."""

import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import (
    LOCKED_STATUSES,
    CaseStatus,
    CommitmentStatus,
    PodCase,
    PodCommitment,
    PodReviewTask,
    ReviewTaskStatus,
)
from src.app.service_pod.core.cases.service import case_blockers
from src.app.service_pod.core.dashboard.schemas import (
    OPEN_PHASES,
    AgingBucket,
    AiActivity,
    AiEvent,
    AiKind,
    CashRunway,
    CashWeek,
    Dashboard,
    EmailHealth,
    MoneyTotal,
    OpenCase,
    Phase,
    PromiseItem,
)
from src.app.service_pod.core.hooks import hooks_for
from src.app.service_pod.core.messaging import service as messaging
from src.app.service_pod.core.messaging.models import Direction, MessageStatus, PodMessage
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import PodKey, WorkflowKey, keys_in

AGING = [
    ("0-7 days", 0, 7),
    ("8-14 days", 8, 14),
    ("15-30 days", 15, 30),
    ("Over 30 days", 31, None),
]
WINDOW = timedelta(days=30)


async def _counts(session: AsyncSession, query: "Select[uuid.UUID, int]") -> dict[uuid.UUID, int]:
    """case_id -> count, from a `select(case_id, count()).group_by(case_id)`."""
    return {case_id: n for case_id, n in (await session.execute(query)).all()}  # noqa: C416


async def _phases(
    session: AsyncSession, access: PodAccess, cases: list[PodCase]
) -> dict[uuid.UUID, Phase]:
    """compose (nothing sent) -> waiting (no reply) -> review (open tasks or blockers) -> ready."""
    ids = [c.id for c in cases]
    sent = await _counts(
        session,
        select(PodMessage.case_id, func.count())
        .where(
            PodMessage.case_id.in_(ids),
            PodMessage.direction == Direction.OUTBOUND,
            PodMessage.status == MessageStatus.SENT,
        )
        .group_by(PodMessage.case_id),
    )
    replies = await _counts(
        session,
        select(PodMessage.case_id, func.count())
        .where(PodMessage.case_id.in_(ids), PodMessage.direction == Direction.INBOUND)
        .group_by(PodMessage.case_id),
    )
    open_tasks = await _counts(
        session,
        select(PodReviewTask.case_id, func.count())
        .where(PodReviewTask.case_id.in_(ids), PodReviewTask.status == ReviewTaskStatus.OPEN)
        .group_by(PodReviewTask.case_id),
    )
    phases: dict[uuid.UUID, Phase] = {}
    for c in cases:
        if c.status in LOCKED_STATUSES:
            phases[c.id] = "closed"
        elif c.status == CaseStatus.APPROVED:
            phases[c.id] = "approved"
        elif (hook := hooks_for(c.workflow).phase) is not None:
            phases[c.id] = cast(
                Phase, await hook(session, c, await case_blockers(session, access, c))
            )
        elif not sent.get(c.id):
            phases[c.id] = "compose"
        elif not replies.get(c.id):
            phases[c.id] = "waiting"
        elif open_tasks.get(c.id) or await case_blockers(session, access, c):
            phases[c.id] = "review"
        else:
            phases[c.id] = "ready"
    return phases


async def _promises(session: AsyncSession) -> tuple[list[MoneyTotal], list[PromiseItem]]:
    rows = (
        await session.execute(
            select(PodCommitment, PodCase, PodSnapshot.currency)
            .join(PodCase, PodCase.id == PodCommitment.case_id)
            .join(PodSnapshot, PodSnapshot.id == PodCase.snapshot_id)
            .where(
                PodCommitment.status == CommitmentStatus.APPROVED,
                PodCase.status != CaseStatus.CANCELLED,
            )
            .order_by(PodCommitment.expected_date)
        )
    ).all()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    dated: list[PromiseItem] = []
    for x, case, currency in rows:
        totals[currency] += x.amount
        if x.expected_date is not None:
            dated.append(
                PromiseItem(
                    case_id=case.id,
                    case_reference=case.reference,
                    case_title=case.title,
                    invoice_number=x.invoice_number,
                    amount=x.amount,
                    currency=currency,
                    expected_date=x.expected_date,
                )
            )
    return [MoneyTotal(currency=k, amount=v) for k, v in sorted(totals.items())], dated


async def _email(session: AsyncSession) -> EmailHealth:
    status = await messaging.email_status()
    settings = get_settings()
    since = utcnow() - WINDOW
    sent_30d = await session.scalar(
        select(func.count()).where(
            PodMessage.direction == Direction.OUTBOUND,
            PodMessage.status == MessageStatus.SENT,
            PodMessage.sent_at >= since,
        )
    )
    original = PodMessage.__table__.alias("original")
    reply_rows = (
        await session.execute(
            select(PodMessage.received_at, original.c.sent_at)
            .join(original, original.c.id == PodMessage.in_reply_to_id)
            .where(PodMessage.direction == Direction.INBOUND, PodMessage.received_at >= since)
        )
    ).all()
    waits = [(r - s).total_seconds() / 3600 for r, s in reply_rows if r and s and r >= s]
    last_reply = await session.scalar(
        select(func.max(PodMessage.received_at)).where(PodMessage.direction == Direction.INBOUND)
    )
    reads = status.provider == "microsoft" and bool(settings.mailbox_poll_seconds)
    return EmailHealth(
        provider=status.provider,
        simulated=status.simulated,
        ready=status.ready,
        problem=status.problem,
        reads_mailbox=reads,
        poll_seconds=settings.mailbox_poll_seconds if reads else None,
        last_reply_at=last_reply,
        sent_30d=sent_30d or 0,
        replies_30d=len(reply_rows),
        avg_reply_hours=round(sum(waits) / len(waits), 1) if waits else None,
    )


AI_EVENTS: dict[str, AiKind] = {
    "pod.reply_read": "reply_read",
    "pod.reply_not_read": "reply_not_read",
    "pod.fpa_commentary": "commentary",
    "pod.reply_imported": "reply_imported",
}


async def _ai_activity(session: AsyncSession) -> AiActivity:
    since = utcnow() - timedelta(days=7)
    grouped = await session.execute(
        select(AuditEvent.event_type, func.count())
        .where(AuditEvent.event_type.in_(AI_EVENTS), AuditEvent.created_at >= since)
        .group_by(AuditEvent.event_type)
    )
    counts = {event: n for event, n in grouped.all()}  # noqa: C416
    rows = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.event_type.in_(AI_EVENTS))
        .order_by(AuditEvent.created_at.desc())
        .limit(8)
    )
    return AiActivity(
        last_7_days={kind: counts.get(event, 0) for event, kind in AI_EVENTS.items()},
        recent=[
            AiEvent(
                at=e.created_at,
                kind=AI_EVENTS[e.event_type],
                summary=str((e.details or {}).get("summary") or e.event_type)[:300],
                case_reference=(e.details or {}).get("run"),
            )
            for e in rows
        ],
    )


async def _cash(session: AsyncSession) -> CashRunway | None:
    case = await session.scalar(
        select(PodCase)
        .where(PodCase.workflow == WorkflowKey.TREASURY, PodCase.status != CaseStatus.CANCELLED)
        .order_by(PodCase.updated_at.desc())
        .limit(1)
    )
    base = ((case.state or {}).get("results") or {}).get("base") if case else None
    if case is None or not base:
        return None
    return CashRunway(
        case_id=case.id,
        case_reference=case.reference,
        currency=str(case.state.get("currency", "")),
        opening=base["opening"],
        buffer=base["buffer"],
        ending_cash=base["ending_cash"],
        first_breach=base.get("first_breach"),
        weeks=[CashWeek(to=w["to"], ending_cash=w["ending_cash"]) for w in base["weeks"]],
    )


async def dashboard(session: AsyncSession, access: PodAccess) -> Dashboard:
    now = utcnow()
    today = now.date()
    cases = list(
        await session.scalars(
            select(PodCase)
            .where(PodCase.workflow.in_(keys_in(PodKey.SERVICE)))  # Service POD cases only
            .order_by(PodCase.created_at)
        )
    )
    phase_of = await _phases(session, access, cases)
    open_cases = [c for c in cases if c.status not in LOCKED_STATUSES]
    closed_30d = sum(
        1
        for c in cases
        if c.status in LOCKED_STATUSES and (c.completed_at or c.updated_at) >= now - WINDOW
    )
    counts: dict[Phase, int] = dict.fromkeys(OPEN_PHASES, 0)
    for c in open_cases:
        counts[phase_of[c.id]] += 1
    counts["closed"] = closed_30d

    def days(c: PodCase) -> int:
        return (now - c.created_at).days

    aging = [
        AgingBucket(
            label=label,
            count=sum(1 for c in open_cases if lo <= days(c) and (hi is None or days(c) <= hi)),
        )
        for label, lo, hi in AGING
    ]
    promised, dated = await _promises(session)
    week = today + timedelta(days=7)
    return Dashboard(
        open_cases=len(open_cases),
        closed_30d=closed_30d,
        phases=counts,
        promised=promised,
        due_this_week=[p for p in dated if today <= p.expected_date <= week][:10],
        overdue_promises=[p for p in dated if p.expected_date < today][:10],
        aging=aging,
        open=[
            OpenCase(
                id=c.id,
                reference=c.reference,
                title=c.title,
                workflow=c.workflow,
                phase=phase_of[c.id],
                days_open=days(c),
            )
            for c in open_cases
        ],
        email=await _email(session),
        ai_activity=await _ai_activity(session),
        cash=await _cash(session),
    )
