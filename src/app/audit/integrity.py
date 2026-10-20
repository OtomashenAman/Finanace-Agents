"""Audit trail tamper evidence and retention.

A database trigger chains every event to the previous one (hash = sha256(content + prev_hash))
and refuses edits and deletes. verify() recomputes the whole chain in the database; purge()
is the only way events leave, and it is itself recorded.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings

# Must stay identical to EVENT_HASH in the audit_integrity migration (the trigger's formula)
_EVENT_HASH = """
    encode(sha256(convert_to(concat_ws('|',
        e.seq::text,
        e.id::text,
        to_char(e.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        e.event_type,
        coalesce(e.ip, ''),
        coalesce(e.user_agent, ''),
        e.details::text,
        coalesce(e.prev_hash, '')
    ), 'UTF8')), 'hex')
"""

_VERIFY = f"""
WITH chain AS (
    SELECT e.seq, e.hash, e.prev_hash,
           {_EVENT_HASH} AS expected,
           lag(e.hash) OVER (ORDER BY e.seq) AS previous,
           row_number() OVER (ORDER BY e.seq) AS position
    FROM audit_events e
)
SELECT count(*) AS checked,
       min(seq) FILTER (
           WHERE hash IS DISTINCT FROM expected
              OR (position > 1 AND prev_hash IS DISTINCT FROM previous)
       ) AS first_broken,
       min(seq) AS first_seq,
       max(seq) AS last_seq
FROM chain
"""  # noqa: S608 - built from constants only, no input


@dataclass(frozen=True)
class ChainCheck:
    checked: int
    valid: bool
    first_broken_seq: int | None  # the first event whose content or link doesn't match
    first_seq: int | None
    last_seq: int | None
    last_hash: str | None
    checked_at: datetime


async def verify(session: AsyncSession) -> ChainCheck:
    row = (await session.execute(text(_VERIFY))).one()
    last_hash = await session.scalar(
        text("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1")
    )
    return ChainCheck(
        checked=row.checked,
        valid=row.first_broken is None,
        first_broken_seq=row.first_broken,
        first_seq=row.first_seq,
        last_seq=row.last_seq,
        last_hash=last_hash,
        checked_at=utcnow(),
    )


@dataclass(frozen=True)
class PurgeResult:
    removed: int
    cutoff: datetime
    anchor_hash: str | None  # hash of the last removed event: the new chain start links to it


async def purge(session: AsyncSession, days: int | None = None) -> PurgeResult:
    """Remove events older than the retention period (commits). The purge is audited."""
    days = days if days is not None else get_settings().audit_retention_days
    cutoff = utcnow() - timedelta(days=days)
    await session.execute(text("SET LOCAL finance_acc.audit_purge = 'on'"))
    removed = (
        await session.execute(
            text("DELETE FROM audit_events WHERE created_at < :cutoff RETURNING seq, hash"),
            {"cutoff": cutoff},
        )
    ).all()
    await session.execute(text("SET LOCAL finance_acc.audit_purge = 'off'"))
    anchor = max(removed, key=lambda r: r.seq).hash if removed else None
    record_event(
        session,
        "audit.purged",
        RequestContext(ip=None, user_agent="retention purge"),
        removed=len(removed),
        cutoff=cutoff.isoformat(),
        retention_days=days,
        anchor_hash=anchor,
    )
    await session.commit()
    return PurgeResult(len(removed), cutoff, anchor)
