import uuid
from typing import Any

from fastapi import APIRouter, Depends, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccess, get_pod_access
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

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}

AccessDependency = Any  # an async FastAPI dependency returning a PodAccess


def build_router(access_dependency: AccessDependency, tag: str) -> APIRouter:
    """The case endpoints, for one POD: the access dependency decides who gets in and which
    POD's cases they see (the Service POD's or the Finance POD's, never both)."""
    router = APIRouter(tags=[tag])

    @router.get("/cases", response_model=list[CaseSummary])
    async def list_cases(
        session: SessionDep,
        access: PodAccess = Depends(access_dependency),
        workflow: WorkflowKey | None = None,
        status: CaseStatus | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> list[CaseSummary]:
        return await service.list_cases(session, access, workflow, status, entity_id)

    @router.post(
        "/cases", response_model=CaseDetail, status_code=status.HTTP_201_CREATED, responses=_ERRORS
    )
    async def create_case(
        body: CaseCreate,
        session: SessionDep,
        ctx: RequestContextDep,
        access: PodAccess = Depends(access_dependency),
    ) -> CaseDetail:
        """Open a case on a snapshot that supplies everything the workflow needs."""
        return await service.create_case(session, access, body, ctx)

    @router.get("/cases/{case_id}", response_model=CaseDetail, responses=_ERRORS)
    async def get_case(
        case_id: uuid.UUID,
        session: SessionDep,
        access: PodAccess = Depends(access_dependency),
    ) -> CaseDetail:
        return await service.get_case(session, access, case_id)

    @router.post("/cases/{case_id}/actions", response_model=CaseDetail, responses=_ERRORS)
    async def case_action(
        case_id: uuid.UUID,
        body: CaseAction,
        session: SessionDep,
        ctx: RequestContextDep,
        access: PodAccess = Depends(access_dependency),
    ) -> CaseDetail:
        """Every change to a case. expected_version must be the version you last saw (409 if
        someone changed it since)."""
        return await service.run_action(session, access, case_id, body, ctx)

    @router.get("/review-queue", response_model=list[ReviewQueueItem])
    async def review_queue(
        session: SessionDep,
        access: PodAccess = Depends(access_dependency),
    ) -> list[ReviewQueueItem]:
        """Open review tasks (ambiguities, disputes, missing documents) on open cases."""
        return await service.review_queue(session, access)

    return router


router = build_router(get_pod_access, "service pod: cases")
