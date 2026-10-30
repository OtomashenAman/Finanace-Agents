"""Shared by the workflows' worklists (AR portfolio, unapplied cash): the snapshot to show
and the cases already open on it."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.access.exceptions import PodForbiddenError
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.access import visible_cases_clause
from src.app.service_pod.core.cases.models import (
    LOCKED_STATUSES,
    CaseStatus,
    PodCase,
)
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import WorkflowKey


class CaseRef(BaseModel):
    id: uuid.UUID
    reference: str
    status: CaseStatus


class InvoiceRow(BaseModel):
    id: str
    number: str
    due_date: date
    balance: Decimal
    days_overdue: int


def case_ref(case: PodCase | None) -> CaseRef | None:
    return CaseRef(id=case.id, reference=case.reference, status=case.status) if case else None


def require_workflow_role(access: PodAccess, workflow: WorkflowKey) -> None:
    if not (access.is_admin or workflow in access.case_workflows):
        raise PodForbiddenError("You have no role in this workflow.")


async def latest_snapshot(
    session: AsyncSession, access: PodAccess, snapshot_id: uuid.UUID | None, needs: set[Collection]
) -> PodSnapshot | None:
    if snapshot_id is not None:
        return await snapshots.get_visible(session, access, snapshot_id)
    query = (
        select(PodSnapshot)
        .where(PodSnapshot.id.not_in(snapshots.archived_ids()))
        .order_by(PodSnapshot.created_at.desc())
        .limit(50)
    )
    if access.entity_ids is not None:
        query = query.where(PodSnapshot.entity_id.in_(access.entity_ids))
    for snap in await session.scalars(query):
        if needs <= {Collection(c) for c in snap.coverage}:
            return snap
    return None


async def open_cases(
    session: AsyncSession, access: PodAccess, workflow: WorkflowKey, entity_id: uuid.UUID
) -> list[PodCase]:
    return list(
        await session.scalars(
            select(PodCase)
            .where(
                visible_cases_clause(access),
                PodCase.workflow == workflow,
                PodCase.entity_id == entity_id,
                PodCase.status.not_in(LOCKED_STATUSES),
            )
            .order_by(PodCase.created_at)
        )
    )
