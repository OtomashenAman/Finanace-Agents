"""Changes the system makes to a case (reading a reply, approving a document, a newer
source): same rules as a person's action. The version grows, a reviewed case goes back to
review, and the audit trail says so."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from src.app.service_pod.core.snapshots.models import PodSnapshot, PodSnapshotArchive

SYSTEM = RequestContext(ip=None, user_agent="service pod")
REVIEWED = frozenset({CaseStatus.AWAITING_FINAL, CaseStatus.APPROVED})


def bump_case(
    session: AsyncSession,
    case: PodCase,
    event: str,
    summary: str,
    *,
    actor_id: uuid.UUID | None = None,
    ctx: RequestContext = SYSTEM,
    content_changed: bool = True,
) -> None:
    """Record a change made outside run_action (caller commits)."""
    reopened = content_changed and case.status in REVIEWED
    if reopened:
        case.status = CaseStatus.IN_REVIEW
    case.version += 1
    record_event(
        session,
        event,
        ctx,
        actor_id=actor_id,
        run=case.reference,
        case_id=str(case.id),
        version=case.version,
        summary=f"{case.reference}: {summary}",
    )
    if reopened:
        record_event(
            session,
            "pod.case_approvals_invalidated",
            ctx,
            actor_id=actor_id,
            run=case.reference,
            case_id=str(case.id),
            summary=f"{case.reference}: content changed after review, back to review",
        )


def raise_task(
    session: AsyncSession,
    case: PodCase,
    kind: ReviewTaskKind,
    detail: str,
    *,
    subject: str | None = None,
    blocking: bool = True,
    requirement: dict[str, Any] | None = None,
) -> PodReviewTask:
    task = PodReviewTask(
        case_id=case.id,
        kind=kind,
        subject=subject,
        detail=detail[:4000],
        blocking=blocking,
        requirement=requirement,
        created_by=None,
    )
    session.add(task)
    return task


async def open_tasks(session: AsyncSession, case: PodCase) -> list[PodReviewTask]:
    return list(
        await session.scalars(
            select(PodReviewTask).where(
                PodReviewTask.case_id == case.id, PodReviewTask.status == ReviewTaskStatus.OPEN
            )
        )
    )


def resolve(task: PodReviewTask, resolution: str, by: uuid.UUID | None = None) -> None:
    task.status = ReviewTaskStatus.RESOLVED
    task.resolution = resolution[:4000]
    task.resolved_by = by
    task.resolved_at = utcnow()


async def satisfy_document_requests(
    session: AsyncSession, case: PodCase, kind: str, invoices: list[str], filename: str
) -> int:
    """An approved document settles the open requests for its kind and invoices (only
    those: a timesheet doesn't answer a request for an invoice copy)."""
    settled = 0
    for task in await open_tasks(session, case):
        req = task.requirement or {}
        same_request = req.get("type") == "document" and req.get("kind") == kind
        if same_request and req.get("invoice") in (None, *invoices):
            resolve(task, f"Approved document {filename}")
            settled += 1
    return settled


async def newer_snapshot(session: AsyncSession, case: PodCase) -> PodSnapshot | None:
    """The latest snapshot of the same company and entity imported after the case's own."""
    current = await session.get(PodSnapshot, case.snapshot_id)
    assert current is not None  # noqa: S101 - RESTRICT foreign key
    return await session.scalar(
        select(PodSnapshot)
        .where(
            PodSnapshot.entity_id == current.entity_id,
            PodSnapshot.company_id == current.company_id,
            PodSnapshot.created_at > current.created_at,
            # an archived snapshot (e.g. a wrong import) never asks cases to refresh
            PodSnapshot.id.not_in(select(PodSnapshotArchive.snapshot_id)),
        )
        .order_by(PodSnapshot.created_at.desc())
        .limit(1)
    )
