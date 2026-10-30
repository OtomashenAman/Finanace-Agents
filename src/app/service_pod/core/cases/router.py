import uuid
from typing import Any

from fastapi import APIRouter, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.core.cases import service
from src.app.service_pod.core.cases.models import CaseStatus
from src.app.service_pod.core.cases.schemas import (
    CaseAction,
    CaseCreate,
    CaseDetail,
    CaseSummary,
    ReviewQueueItem,
)
from src.app.service_pod.core.workflows import WorkflowKey

router = APIRouter(tags=["service pod: cases"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}


@router.get("/cases", response_model=list[CaseSummary])
async def list_cases(
    session: SessionDep,
    access: PodAccessDep,
    workflow: WorkflowKey | None = None,
    status: CaseStatus | None = None,
    entity_id: uuid.UUID | None = None,
) -> list[CaseSummary]:
    return await service.list_cases(session, access, workflow, status, entity_id)


@router.post(
    "/cases", response_model=CaseDetail, status_code=status.HTTP_201_CREATED, responses=_ERRORS
)
async def create_case(
    body: CaseCreate, session: SessionDep, access: PodAccessDep, ctx: RequestContextDep
) -> CaseDetail:
    """Open a case on a snapshot that supplies everything the workflow needs."""
    return await service.create_case(session, access, body, ctx)


@router.get("/cases/{case_id}", response_model=CaseDetail, responses=_ERRORS)
async def get_case(case_id: uuid.UUID, session: SessionDep, access: PodAccessDep) -> CaseDetail:
    return await service.get_case(session, access, case_id)


@router.post("/cases/{case_id}/actions", response_model=CaseDetail, responses=_ERRORS)
async def case_action(
    case_id: uuid.UUID,
    body: CaseAction,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> CaseDetail:
    """Every change to a case. expected_version must be the version you last saw (409 if
    someone changed it since)."""
    return await service.run_action(session, access, case_id, body, ctx)


@router.get("/review-queue", response_model=list[ReviewQueueItem])
async def review_queue(session: SessionDep, access: PodAccessDep) -> list[ReviewQueueItem]:
    """Open review tasks (ambiguities, disputes, missing documents) on your cases."""
    return await service.review_queue(session, access)
