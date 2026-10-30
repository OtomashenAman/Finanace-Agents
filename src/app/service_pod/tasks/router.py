import uuid
from typing import Any

from fastapi import APIRouter, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.access.service import PodAccessDep
from src.app.service_pod.tasks import service
from src.app.service_pod.tasks.models import TaskStatus
from src.app.service_pod.tasks.schemas import TaskAction, TaskCreate, TaskOut

router = APIRouter(tags=["service pod: posting tasks"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    session: SessionDep, access: PodAccessDep, status: TaskStatus | None = None
) -> list[TaskOut]:
    """The manual QuickBooks task queue (Finance Admins with posting rights)."""
    return await service.list_tasks(session, access, status)


@router.post(
    "/cases/{case_id}/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def propose_task(
    case_id: uuid.UUID,
    body: TaskCreate,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> TaskOut:
    return await service.propose_task(session, access, case_id, body, ctx)


@router.post("/tasks/{task_id}/actions", response_model=TaskOut, responses=_ERRORS)
async def task_action(
    task_id: uuid.UUID,
    body: TaskAction,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> TaskOut:
    """approve / record (with the QuickBooks transaction ID) / verify (with a fresh snapshot)
    / cancel."""
    return await service.run_action(session, access, task_id, body, ctx)
