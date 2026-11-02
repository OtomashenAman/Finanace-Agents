import uuid
from typing import Any

from fastapi import APIRouter, status

import src.app.finance_pod.flows  # noqa: F401 - registers every Finance POD workflow
from src.app.auth.dependencies import AdminUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.finance_pod import service
from src.app.finance_pod.access import FinanceAccessDep, get_finance_access
from src.app.finance_pod.schemas import (
    AssignmentCreate,
    AssignmentOut,
    CapacityOut,
    FinanceDashboard,
    FinanceMe,
)
from src.app.service_pod.core.access.router import build_router as build_access_router
from src.app.service_pod.core.cases.router import build_router as build_cases_router
from src.app.service_pod.core.registry import ROUTERS
from src.app.service_pod.core.workflows import PodKey

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}

router = APIRouter(prefix="/finance")
# The shared case engine, behind the Finance POD's own access (capacities, its cases only)
router.include_router(build_access_router(get_finance_access, "finance pod: access"))
router.include_router(build_cases_router(get_finance_access, "finance pod: cases"))

own = APIRouter(tags=["finance pod"])


@own.get("/me", response_model=FinanceMe)
async def finance_me(session: SessionDep, access: FinanceAccessDep) -> FinanceMe:
    """The viewer's capacities, and the workflows they may open a case of."""
    return await service.me(session, access)


@own.get("/dashboard", response_model=FinanceDashboard)
async def finance_dashboard(session: SessionDep, access: FinanceAccessDep) -> FinanceDashboard:
    """Each workflow's cases and measures, and the steps waiting on the viewer."""
    return await service.dashboard(session, access)


@own.get("/capacities/catalog", response_model=list[CapacityOut])
async def capacity_catalog(_: FinanceAccessDep) -> list[CapacityOut]:
    return service.catalog()


@own.get("/capacities", response_model=list[AssignmentOut])
async def list_capacities(session: SessionDep, _: AdminUser) -> list[AssignmentOut]:
    """Who holds which capacity (Finance Admin only)."""
    return await service.list_assignments(session)


@own.post(
    "/capacities",
    response_model=AssignmentOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def grant_capacity(
    body: AssignmentCreate, session: SessionDep, admin: AdminUser, ctx: RequestContextDep
) -> AssignmentOut:
    return await service.grant(session, admin, body, ctx)


@own.delete(
    "/capacities/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS
)
async def revoke_capacity(
    assignment_id: uuid.UUID, session: SessionDep, admin: AdminUser, ctx: RequestContextDep
) -> None:
    await service.revoke(session, admin, assignment_id, ctx)


router.include_router(own)
for workflow_router in ROUTERS[PodKey.FINANCE]:
    router.include_router(workflow_router)
