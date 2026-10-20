"""My Worklist: what needs the viewer now, computed live from runs, data sources and users."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.runs import service as runs
from src.app.auth import service as auth
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.data_sources import service as data_sources
from src.app.data_sources.models import SourceStatus
from src.app.users import service as users
from src.app.worklist.schemas import WorkItem, Worklist

STALE_DRAFT_DAYS = 7

# Most urgent first; within a kind, overdue and high priority first, then oldest
_ORDER = {
    "approve": 0,
    "changes_requested": 1,
    "validation_failed": 2,
    "password_reset": 3,
    "locked_account": 3,
    "data_source": 4,
    "ready_to_submit": 5,
    "draft": 6,
}

_RUN_ACTIONS = {
    "approve": "Review",
    "changes_requested": "Fix & resubmit",
    "validation_failed": "Fix input",
    "ready_to_submit": "Review & submit",
    "draft": "Continue",
}

_SOURCE_PROBLEM = {
    SourceStatus.NEEDS_REAUTH: ("QuickBooks access expired", "Re-authorize"),
    SourceStatus.ERROR: ("Last sync failed", "Sync again"),
    SourceStatus.PENDING_AUTH: ("Connection not finished", "Authorize"),
}


def _run_item(work: runs.RunWork, now_overdue: bool, *, admin: bool) -> WorkItem:
    s = work.summary
    context = " · ".join(
        part
        for part in (
            s.agent_name,
            s.entity.code if s.entity else None,
            s.preparer.full_name if admin else None,
        )
        if part
    )
    detail = work.note
    if work.kind == "draft" and now_overdue:
        detail = f"Not touched for more than {STALE_DRAFT_DAYS} days"
    return WorkItem(
        kind=work.kind,
        title=f"{s.reference} · {s.business_reference}" if s.business_reference else s.reference,
        detail=detail,
        context=context or None,
        since=work.since,
        overdue=now_overdue,
        high_priority=s.priority == "high",
        action_label=_RUN_ACTIONS.get(work.kind),
        link=f"/catalog/{s.agent_key}/runs/{s.id}",
    )


async def get_worklist(session: AsyncSession, user: User) -> Worklist:
    now = utcnow()
    sla = timedelta(hours=get_settings().review_sla_hours)
    stale = timedelta(days=STALE_DRAFT_DAYS)
    admin = user.role == UserRole.FINANCE_ADMIN

    action: list[WorkItem] = []
    waiting: list[WorkItem] = []
    info: list[WorkItem] = []

    for work in await runs.work_runs(session, user):
        if work.kind == "approve":
            overdue = work.since + sla < now
        elif work.kind == "draft":
            overdue = work.since + stale < now
        else:
            overdue = False
        item = _run_item(work, overdue, admin=admin)
        if work.kind == "waiting":
            item.overdue = work.since + sla < now
            item.detail = f"Waiting for a Finance Admin · {work.note}"
            waiting.append(item)
        else:
            action.append(item)

    for source, owner in await data_sources.attention_sources(session, None if admin else user.id):
        problem, label = _SOURCE_PROBLEM.get(source.status, ("Needs attention", "Open"))
        detail = f"{problem}: {source.last_error}" if source.last_error else problem
        if source.owner_id == user.id:
            action.append(
                WorkItem(
                    kind="data_source",
                    title=source.name,
                    detail=detail,
                    context="Your data source",
                    since=source.updated_at,
                    overdue=False,
                    high_priority=source.status == SourceStatus.NEEDS_REAUTH,
                    action_label=label,
                    link="/data-sources",
                )
            )
        elif admin:
            info.append(
                WorkItem(
                    kind="user_data_source",
                    title=source.name,
                    detail=f"{detail}. Only {owner.full_name} can fix it (their own Intuit app).",
                    context=f"{owner.full_name} · {owner.email}",
                    since=source.updated_at,
                    overdue=False,
                    high_priority=False,
                    action_label=None,
                    link="/admin/data-sources",
                )
            )

    if admin:
        for request, requester in await auth.open_reset_requests(session):
            action.append(
                WorkItem(
                    kind="password_reset",
                    title=requester.full_name,
                    detail="Forgot their password. Set a new one and share it with them securely.",
                    context=requester.email,
                    since=request.created_at,
                    overdue=False,
                    high_priority=False,
                    action_label="Set password",
                    link="/admin/users",
                )
            )
        for locked in await users.locked_users(session):
            action.append(
                WorkItem(
                    kind="locked_account",
                    title=locked.full_name,
                    detail="Locked after repeated failed sign-ins. A new password unlocks it.",
                    context=locked.email,
                    since=locked.updated_at,
                    overdue=False,
                    high_priority=False,
                    action_label="Unlock",
                    link="/admin/users",
                )
            )

    action.sort(key=lambda i: (_ORDER.get(i.kind, 9), not i.overdue, not i.high_priority, i.since))
    waiting.sort(key=lambda i: i.since)
    return Worklist(
        action=action,
        waiting=waiting,
        info=info,
        review_sla_hours=get_settings().review_sla_hours,
        stale_draft_days=STALE_DRAFT_DAYS,
    )
