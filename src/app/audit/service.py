import base64
import contextlib
import csv
import io
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent
from src.app.agent_catalog.runs.models import AgentRun
from src.app.audit.exceptions import InvalidCursorError
from src.app.audit.labels import (
    FAILURE_EVENTS,
    AuditCategory,
    category_of,
    describe,
    prefixes_of,
)
from src.app.audit.models import AuditEvent
from src.app.audit.schemas import AuditEventOut, AuditPage, AuditPerson, AuditRunLink
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext


def record_event(
    session: AsyncSession,
    event_type: str,
    ctx: RequestContext,
    actor_id: uuid.UUID | None = None,
    **details: Any,
) -> None:
    """Add an audit event to the current transaction (caller commits)."""
    session.add(
        AuditEvent(
            event_type=event_type,
            actor_id=actor_id,
            ip=ctx.ip,
            user_agent=ctx.user_agent[:512] if ctx.user_agent else None,
            details=details,
        )
    )


# --- reading the trail ------------------------------------------------------------------

PAGE_SIZE = 50
EXPORT_LIMIT = 10_000


@dataclass(frozen=True)
class AuditFilters:
    category: AuditCategory | None = None
    actor_id: uuid.UUID | None = None  # Finance Admin only
    run: str | None = None  # e.g. "RUN-01006"
    since: date | None = None
    until: date | None = None  # inclusive
    failures_only: bool = False


def _is_admin(user: User) -> bool:
    return user.role == UserRole.FINANCE_ADMIN


def _scoped(viewer: User) -> Select[AuditEvent]:
    """A Finance Admin sees everything. A user sees their own actions, what was done to their
    account, and every event on their own runs (e.g. the admin's decision)."""
    query = select(AuditEvent)
    if _is_admin(viewer):
        return query
    own_runs = select(AgentRun.reference_sql()).where(AgentRun.preparer_id == viewer.id)
    return query.where(
        or_(
            AuditEvent.actor_id == viewer.id,
            AuditEvent.details["user_id"].astext == str(viewer.id),
            AuditEvent.details["run"].astext.in_(own_runs),
        )
    )


def _filtered(viewer: User, f: AuditFilters) -> Select[AuditEvent]:
    query = _scoped(viewer)
    if f.category is not None:
        query = query.where(
            or_(*(AuditEvent.event_type.startswith(p) for p in prefixes_of(f.category)))
        )
    if f.actor_id is not None and _is_admin(viewer):
        query = query.where(AuditEvent.actor_id == f.actor_id)
    if f.run:
        query = query.where(AuditEvent.details["run"].astext == f.run.strip().upper())
    if f.since is not None:
        query = query.where(AuditEvent.created_at >= datetime.combine(f.since, time(), UTC))
    if f.until is not None:
        end = datetime.combine(f.until + timedelta(days=1), time(), UTC)
        query = query.where(AuditEvent.created_at < end)
    if f.failures_only:
        query = query.where(AuditEvent.event_type.in_(FAILURE_EVENTS))
    return query


def _encode_cursor(event: AuditEvent) -> str:
    raw = f"{event.created_at.isoformat()}|{event.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, _, event_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(at), uuid.UUID(event_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError from exc


async def _present(
    session: AsyncSession, viewer: User, events: list[AuditEvent]
) -> list[AuditEventOut]:
    """Resolve people and runs for display; hide other people's IP and browser from users."""
    user_ids = {e.actor_id for e in events if e.actor_id}
    for e in events:
        with contextlib.suppress(ValueError, TypeError):
            user_ids.add(uuid.UUID(str(e.details.get("user_id"))))
    people = {
        u.id: AuditPerson(id=u.id, full_name=u.full_name, email=u.email)
        for u in await session.scalars(select(User).where(User.id.in_(user_ids)))
    }

    refs = {str(e.details["run"]) for e in events if e.details.get("run")}
    run_query = select(AgentRun.id, AgentRun.reference_sql(), Agent.key).join(
        Agent, Agent.id == AgentRun.agent_id
    )
    if not _is_admin(viewer):
        run_query = run_query.where(AgentRun.preparer_id == viewer.id)
    runs = (
        {
            ref: AuditRunLink(id=run_id, reference=ref, agent_key=key)
            for run_id, ref, key in await session.execute(
                run_query.where(AgentRun.reference_sql().in_(refs))
            )
        }
        if refs
        else {}
    )

    out = []
    for e in events:
        subject = None
        with contextlib.suppress(ValueError, TypeError):
            subject = people.get(uuid.UUID(str(e.details.get("user_id"))))
        sees_origin = _is_admin(viewer) or e.actor_id == viewer.id
        out.append(
            AuditEventOut(
                id=e.id,
                created_at=e.created_at,
                event_type=e.event_type,
                category=category_of(e.event_type),
                summary=describe(e.event_type, e.details, subject.full_name if subject else None),
                outcome="failure" if e.event_type in FAILURE_EVENTS else "success",
                actor=people.get(e.actor_id) if e.actor_id else None,
                subject_user=subject,
                run=runs.get(str(e.details.get("run"))) if e.details.get("run") else None,
                ip=e.ip if sees_origin else None,
                user_agent=e.user_agent if sees_origin else None,
                details=e.details,
            )
        )
    return out


async def list_events(
    session: AsyncSession, viewer: User, filters: AuditFilters, cursor: str | None
) -> AuditPage:
    """Newest first, PAGE_SIZE at a time (keyset pagination: stable while events arrive)."""
    query = _filtered(viewer, filters)
    if cursor:
        at, event_id = _decode_cursor(cursor)
        query = query.where(tuple_(AuditEvent.created_at, AuditEvent.id) < tuple_(at, event_id))
    events = list(
        await session.scalars(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(PAGE_SIZE + 1)
        )
    )
    more = len(events) > PAGE_SIZE
    events = events[:PAGE_SIZE]
    return AuditPage(
        items=await _present(session, viewer, events),
        next_cursor=_encode_cursor(events[-1]) if more else None,
    )


async def run_timeline(session: AsyncSession, viewer: User, reference: str) -> list[AuditEventOut]:
    """Every event on one run, oldest first (access to the run is checked by the caller)."""
    events = list(
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.details["run"].astext == reference)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )
    return await _present(session, viewer, events)


def _csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    # Spreadsheets run cells starting with these as formulas (CSV injection)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


async def export_csv(
    session: AsyncSession, admin: User, filters: AuditFilters, ctx: RequestContext
) -> str:
    """Up to EXPORT_LIMIT events matching the filters, newest first. The export is audited."""
    events = list(
        await session.scalars(
            _filtered(admin, filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(EXPORT_LIMIT)
        )
    )
    rows = await _present(session, admin, events)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["time_utc", "category", "event", "summary", "outcome", "actor", "subject", "run", "ip",
         "user_agent", "details"]
    )  # fmt: skip
    for r in rows:
        writer.writerow(
            _csv_cell(v)
            for v in (
                r.created_at.astimezone(UTC).isoformat(),
                r.category.value if r.category else "",
                r.event_type,
                r.summary,
                r.outcome,
                r.actor.email if r.actor else "",
                r.subject_user.email if r.subject_user else "",
                r.details.get("run", ""),
                r.ip,
                r.user_agent,
                json.dumps(r.details, sort_keys=True, default=str),
            )
        )
    record_event(
        session,
        "audit.exported",
        ctx,
        actor_id=admin.id,
        rows=len(rows),
        filters={k: str(v) for k, v in asdict(filters).items() if v not in (None, False)},
    )
    await session.commit()
    return buffer.getvalue()
