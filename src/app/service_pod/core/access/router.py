import uuid
from typing import Any

from fastapi import APIRouter

from src.app.auth.dependencies import AdminUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access import service
from src.app.service_pod.core.access.schemas import PodAssignmentsUpdate, PodUserAccess, WorkflowOut
from src.app.service_pod.core.access.service import PodAccessDep

router = APIRouter(tags=["service pod: access"])

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (403, 422)}


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(access: PodAccessDep) -> list[WorkflowOut]:
    """The five workflows with the signed-in user's capacities in each."""
    return service.workflows_for(access)


@router.get("/assignments", response_model=list[PodUserAccess], responses=_ERRORS)
async def list_assignments(session: SessionDep, _: AdminUser) -> list[PodUserAccess]:
    return await service.list_user_access(session)


@router.put("/assignments/{user_id}", response_model=PodUserAccess, responses=_ERRORS)
async def set_assignments(
    user_id: uuid.UUID,
    body: PodAssignmentsUpdate,
    session: SessionDep,
    admin: AdminUser,
    ctx: RequestContextDep,
) -> PodUserAccess:
    """Replace a user's Service POD roles (Finance Admin only)."""
    return await service.set_user_access(session, user_id, body.assignments, admin, ctx)
