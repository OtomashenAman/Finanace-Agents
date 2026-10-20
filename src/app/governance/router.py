from typing import Any

from fastapi import APIRouter

from src.app.auth.dependencies import AdminUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.governance import service
from src.app.governance.schemas import (
    ApprovalMatrixOut,
    ApprovalMatrixUpdate,
    OrgSettingsOut,
    OrgSettingsUpdate,
    PolicyOut,
    PolicyUpdate,
    PolicyVersionOut,
)

# Finance Admin only
router = APIRouter(prefix="/admin/governance", tags=["governance"])

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (404, 422)}


@router.get("/settings", response_model=OrgSettingsOut)
async def get_settings(session: SessionDep, _: AdminUser) -> OrgSettingsOut:
    return await service.get_settings(session)


@router.put("/settings", response_model=OrgSettingsOut)
async def update_settings(
    body: OrgSettingsUpdate, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> OrgSettingsOut:
    """Off: nobody approves their own run, Finance Admins included (full maker-checker)."""
    return await service.update_settings(session, body.allow_admin_self_approval, admin, ctx)


@router.get("/policies", response_model=list[PolicyOut])
async def list_policies(session: SessionDep, _: AdminUser) -> list[PolicyOut]:
    """Each agent's adjustable thresholds and the version in force."""
    return await service.list_policies(session)


@router.get("/policies/{key}/versions", response_model=list[PolicyVersionOut], responses=_ERRORS)
async def policy_history(key: str, session: SessionDep, _: AdminUser) -> list[PolicyVersionOut]:
    return await service.policy_history(session, key)


@router.put("/policies/{key}", response_model=PolicyOut, responses=_ERRORS)
async def save_policy(
    key: str, body: PolicyUpdate, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> PolicyOut:
    """Saves a new version; analyses from now on use it (earlier runs keep theirs)."""
    return await service.save_policy(session, key, body.values, body.note, admin, ctx)


@router.get("/approval-matrix", response_model=list[ApprovalMatrixOut])
async def list_matrices(session: SessionDep, _: AdminUser) -> list[ApprovalMatrixOut]:
    return await service.list_matrices(session)


@router.put("/approval-matrix/{key}", response_model=ApprovalMatrixOut, responses=_ERRORS)
async def set_matrix(
    key: str,
    body: ApprovalMatrixUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    admin: AdminUser,
) -> ApprovalMatrixOut:
    """Replace the agent's amount tiers (runs already submitted keep their tier)."""
    return await service.set_matrix(session, key, body.tiers, admin, ctx)
