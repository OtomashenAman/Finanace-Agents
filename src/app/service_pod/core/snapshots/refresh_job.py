"""Fresh books every night, without anyone clicking.

Every QuickBooks company already frozen into the Service POD is synced again and frozen
into a new snapshot, with the same legal entity, currency and basis as its latest snapshot.
The people working the cases share these snapshots, so they never need a QuickBooks
connection of their own. At most one per company per day: a snapshot is dated by its sync
(AR aging counts from that date), so books already frozen today are left as they are. Open
cases stay on the snapshot they were opened on, as always: moving
a case to newer books is the case's own "refresh source" step.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.data_sources import service as data_sources
from src.app.data_sources.models import DataSource, SourceKind, SourceStatus
from src.app.jobs.queue import JobContext, daily, handler
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot, PodSnapshotSource
from src.app.service_pod.core.snapshots.schemas import (
    QuickBooksSnapshotRequest,
    SnapshotImportResult,
)
from src.app.service_pod.core.workflows import WorkflowKey

log = logging.getLogger("finance_acc.pod")

REFRESH_JOB = "pod.refresh_snapshots"
_SYSTEM = RequestContext(ip=None, user_agent="background worker: nightly books refresh")


async def refresh_source(
    session: AsyncSession, source_id: uuid.UUID
) -> SnapshotImportResult | None:
    """Sync one QuickBooks company and freeze it again like its latest snapshot (commits).
    None when it was never frozen into the Service POD, was already frozen today, or its
    owner can't act any more."""
    source = await session.get(DataSource, source_id)
    if source is None or source.kind != SourceKind.QUICKBOOKS:
        return None
    latest = await session.scalar(
        select(PodSnapshot)
        .join(PodSnapshotSource, PodSnapshotSource.snapshot_id == PodSnapshot.id)
        .where(
            PodSnapshotSource.data_source_id == source.id,
            PodSnapshot.id.not_in(snapshots.archived_ids()),
        )
        .order_by(PodSnapshot.created_at.desc())
        .limit(1)
    )
    owner = await session.get(User, source.owner_id)
    if latest is None or owner is None or not owner.is_active:
        return None
    if latest.as_of >= utcnow().date():
        return None  # already fresh today (e.g. frozen by hand)
    # The connection is its owner's: the refresh acts as them, as if they had clicked
    await data_sources.sync_source(session, owner, source.id, _SYSTEM)
    access = PodAccess(user=owner, workflows=frozenset(WorkflowKey))
    body = QuickBooksSnapshotRequest(
        data_source_id=source.id,
        entity_id=latest.entity_id,
        currency=latest.currency,
        basis=latest.basis,
    )
    return await snapshots.import_quickbooks(session, access, body, _SYSTEM)


@daily(REFRESH_JOB)
@handler(REFRESH_JOB)
async def refresh_snapshots(
    session: AsyncSession, payload: dict[str, Any], ctx: JobContext
) -> None:
    """Refresh every connected QuickBooks company. One company failing (e.g. it needs
    reconnecting, which the dashboard then shows) doesn't stop the others."""
    source_ids = list(
        await session.scalars(
            select(DataSource.id).where(
                DataSource.kind == SourceKind.QUICKBOOKS,
                DataSource.status == SourceStatus.CONNECTED,
            )
        )
    )
    for source_id in source_ids:
        try:
            result = await refresh_source(session, source_id)
        except Exception:
            await session.rollback()
            log.warning("nightly refresh of QuickBooks source %s failed", source_id, exc_info=True)
            continue
        if result is not None:
            log.info(
                "nightly refresh of QuickBooks source %s: snapshot %s (%s)",
                source_id,
                result.snapshot.id,
                "new" if result.created else "unchanged",
            )
