"""Deleting a snapshot with everything that depends on it (admin only): the snapshots built on
it, the cases on any of them and all their children. Used for wrong imports, test data and
when a data source or a user's data is removed. The audit trail keeps the record.

Order matters (some links refuse deletion): packs, commitments and message reply links go
first, then the cases (their other children cascade), then the snapshots from the newest.
A posting task of a kept case that was verified by a deleted snapshot keeps its status; its
link to the snapshot is cleared and the verification notes say so.
"""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.data_sources import service as data_sources_service
from src.app.data_sources.models import DataSource
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodApproval,
    PodCase,
    PodCommitment,
    PodReviewTask,
)
from src.app.service_pod.core.messaging.models import PodArtifact, PodMessage
from src.app.service_pod.core.snapshots.models import PodSnapshot, PodSnapshotSource
from src.app.service_pod.core.snapshots.schemas import PurgeCase, PurgePreview, PurgeSnapshot
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskStatus


class PurgeConfirmationError(AppError):
    status_code = 422
    code = "purge_not_confirmed"


async def _with_descendants(session: AsyncSession, roots: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """The snapshots and every snapshot built on them (bank statements extend a parent)."""
    found: list[uuid.UUID] = []
    frontier = list(dict.fromkeys(roots))
    while frontier:
        found.extend(i for i in frontier if i not in found)
        children = await session.scalars(
            select(PodSnapshot.id).where(PodSnapshot.parent_id.in_(frontier))
        )
        frontier = [c for c in children if c not in found]
    return found


async def _count(session: AsyncSession, model: Any, case_ids: list[uuid.UUID]) -> int:
    if not case_ids:
        return 0
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.case_id.in_(case_ids))
        )
        or 0
    )


async def preview_cases(
    session: AsyncSession, case_ids: list[uuid.UUID], snapshot_ids: list[uuid.UUID]
) -> PurgePreview:
    cases = (
        list(
            await session.scalars(
                select(PodCase).where(PodCase.id.in_(case_ids)).order_by(PodCase.created_at)
            )
        )
        if case_ids
        else []
    )
    snaps = (
        list(
            await session.scalars(
                select(PodSnapshot)
                .where(PodSnapshot.id.in_(snapshot_ids))
                .order_by(PodSnapshot.created_at)
            )
        )
        if snapshot_ids
        else []
    )
    verified_elsewhere = (
        int(
            await session.scalar(
                select(func.count())
                .select_from(PodPostingTask)
                .where(
                    PodPostingTask.verification_snapshot_id.in_(snapshot_ids),
                    PodPostingTask.case_id.not_in(case_ids or [uuid.uuid4()]),
                )
            )
            or 0
        )
        if snapshot_ids
        else 0
    )
    verified = (
        int(
            await session.scalar(
                select(func.count())
                .select_from(PodPostingTask)
                .where(
                    PodPostingTask.case_id.in_(case_ids),
                    PodPostingTask.status == TaskStatus.VERIFIED,
                )
            )
            or 0
        )
        if case_ids
        else 0
    )
    return PurgePreview(
        snapshots=[
            PurgeSnapshot(
                id=s.id,
                company_name=s.company_name,
                as_of=s.as_of,
                source_type=s.source_type.value,
                is_demo=s.is_demo,
            )
            for s in snaps
        ],
        cases=[
            PurgeCase(
                id=c.id,
                reference=c.reference,
                title=c.title,
                workflow=c.workflow,
                status=c.status.value,
            )
            for c in cases
        ],
        messages=await _count(session, PodMessage, case_ids),
        documents=await _count(session, PodArtifact, case_ids),
        posting_tasks=await _count(session, PodPostingTask, case_ids),
        review_tasks=await _count(session, PodReviewTask, case_ids),
        commitments=await _count(session, PodCommitment, case_ids),
        approvals=await _count(session, PodApproval, case_ids),
        verified_elsewhere=verified_elsewhere,
        # Real evidence: approved or finished work, or a verified posting, on real books
        evidence=any(not s.is_demo for s in snaps)
        and (
            verified > 0
            or any(c.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED) for c in cases)
        ),
        all_demo=bool(snaps) and all(s.is_demo for s in snaps),
    )


async def snapshot_preview(session: AsyncSession, snapshot_id: uuid.UUID) -> PurgePreview:
    snapshot_ids = await _with_descendants(session, [snapshot_id])
    case_ids = list(
        await session.scalars(select(PodCase.id).where(PodCase.snapshot_id.in_(snapshot_ids)))
    )
    return await preview_cases(session, case_ids, snapshot_ids)


async def purge_cases(session: AsyncSession, case_ids: list[uuid.UUID]) -> None:
    """Delete the cases and all their children (caller records and commits)."""
    if not case_ids:
        return
    from src.app.service_pod.flows.reporting.models import PodReportPack

    await session.execute(delete(PodReportPack).where(PodReportPack.case_id.in_(case_ids)))
    await session.execute(delete(PodCommitment).where(PodCommitment.case_id.in_(case_ids)))
    await session.execute(
        update(PodMessage).where(PodMessage.case_id.in_(case_ids)).values(in_reply_to_id=None)
    )
    await session.execute(delete(PodCase).where(PodCase.id.in_(case_ids)))


async def purge_snapshots(session: AsyncSession, snapshot_ids: list[uuid.UUID]) -> None:
    """Delete snapshots (with their descendants already included) and the cases on them."""
    if not snapshot_ids:
        return
    case_ids = list(
        await session.scalars(select(PodCase.id).where(PodCase.snapshot_id.in_(snapshot_ids)))
    )
    await purge_cases(session, case_ids)
    tasks = await session.scalars(
        select(PodPostingTask).where(PodPostingTask.verification_snapshot_id.in_(snapshot_ids))
    )
    for task in tasks:
        task.verification = {
            **(task.verification or {}),
            "source_deleted": f"The verifying snapshot was deleted on {utcnow().date()}.",
        }
        task.verification_snapshot_id = None
    await session.flush()
    # The database refuses deleting snapshots unless this transaction says it's this path
    await session.execute(text("SET LOCAL finance_acc.pod_snapshot_delete = 'on'"))
    # Snapshots stay immutable (no UPDATE): delete the newest first, so a snapshot built on
    # another always goes before it
    newest_first = await session.scalars(
        select(PodSnapshot.id)
        .where(PodSnapshot.id.in_(snapshot_ids))
        .order_by(PodSnapshot.created_at.desc())
    )
    for snapshot_id in list(newest_first):
        await session.execute(delete(PodSnapshot).where(PodSnapshot.id == snapshot_id))


async def purge_snapshot(
    session: AsyncSession,
    access: PodAccess,
    snapshot_id: uuid.UUID,
    reason: str,
    confirm: str,
    ctx: RequestContext,
) -> PurgePreview:
    """Delete a snapshot and everything that depends on it, once the admin typed its company
    name. Returns what was deleted."""
    snapshot = await session.get(PodSnapshot, snapshot_id)
    if snapshot is None:
        from src.app.service_pod.core.snapshots.exceptions import (
            SnapshotNotFoundError,
        )

        raise SnapshotNotFoundError
    if confirm.strip().casefold() != snapshot.company_name.strip().casefold():
        raise PurgeConfirmationError("Type the company name exactly to confirm the deletion.")
    gone = await snapshot_preview(session, snapshot_id)
    record_event(
        session,
        "pod.snapshot_purged",
        ctx,
        actor_id=access.user.id,
        snapshot_id=str(snapshot.id),
        sha256=snapshot.sha256,
        reason=reason,
        company=snapshot.company_name,
        snapshots=[str(s.id) for s in gone.snapshots],
        cases=[c.reference for c in gone.cases],
        evidence=gone.evidence,
        summary=(
            f"Deleted the snapshot of {snapshot.company_name} as of {snapshot.as_of} with "
            f"{len(gone.snapshots) - 1} later snapshot(s) and {len(gone.cases)} case(s): {reason}"
        ),
    )
    await purge_snapshots(session, [s.id for s in gone.snapshots])
    await session.commit()
    return gone


# --- a data source's snapshots ---------------------------------------------------------


async def source_snapshot_ids(session: AsyncSession, source_id: uuid.UUID) -> list[uuid.UUID]:
    """The snapshots read from the data source, and every snapshot built on them."""
    linked = await session.scalars(
        select(PodSnapshotSource.snapshot_id).where(PodSnapshotSource.data_source_id == source_id)
    )
    return await _with_descendants(session, list(linked))


async def data_source_preview(session: AsyncSession, source_id: uuid.UUID) -> PurgePreview:
    snapshot_ids = await source_snapshot_ids(session, source_id)
    case_ids = (
        list(await session.scalars(select(PodCase.id).where(PodCase.snapshot_id.in_(snapshot_ids))))
        if snapshot_ids
        else []
    )
    return await preview_cases(session, case_ids, snapshot_ids)


async def remove_for_data_source(
    session: AsyncSession, user: User, source: DataSource, ctx: RequestContext
) -> None:
    """Registered with data sources: deleting a source "with dependents" removes the POD
    snapshots read from it and everything on them (the caller commits)."""
    snapshot_ids = await source_snapshot_ids(session, source.id)
    if not snapshot_ids:
        return
    gone = await data_source_preview(session, source.id)
    record_event(
        session,
        "pod.data_source_purged",
        ctx,
        actor_id=user.id,
        source_id=str(source.id),
        snapshots=[str(s.id) for s in gone.snapshots],
        cases=[c.reference for c in gone.cases],
        evidence=gone.evidence,
        summary=(
            f"Deleted {len(gone.snapshots)} snapshot(s) and {len(gone.cases)} case(s) made from "
            f"the data source {source.name}"
        ),
    )
    await purge_snapshots(session, snapshot_ids)


data_sources_service.DEPENDENTS.append(remove_for_data_source)
