import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from src.app.auth.dependencies import AdminUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.users import service
from src.app.users.schemas import (
    AssignmentsUpdate,
    ManagedUser,
    PasswordReset,
    UserCreate,
    UserUpdate,
)

# Finance Admin only: every endpoint depends on AdminUser
router = APIRouter(prefix="/users", tags=["users"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409)
}


@router.get("", response_model=list[ManagedUser], responses=_ERRORS)
async def list_users(
    session: SessionDep, _: AdminUser, search: str | None = None
) -> list[ManagedUser]:
    """All users with their agent assignments; `search` matches email or name."""
    return await service.list_users(session, search)


@router.post("", response_model=ManagedUser, status_code=status.HTTP_201_CREATED, responses=_ERRORS)
async def create_user(
    body: UserCreate, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> ManagedUser:
    return await service.create_user(session, body, admin, ctx)


@router.get("/{user_id}", response_model=ManagedUser, responses=_ERRORS)
async def get_user(user_id: uuid.UUID, session: SessionDep, _: AdminUser) -> ManagedUser:
    return await service.get_user(session, user_id)


@router.patch("/{user_id}", response_model=ManagedUser, responses=_ERRORS)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    admin: AdminUser,
) -> ManagedUser:
    """Rename, change role or (de)activate. Deactivating signs the user out everywhere."""
    return await service.update_user(session, user_id, body, admin, ctx)


@router.post("/{user_id}/password", response_model=ManagedUser, responses=_ERRORS)
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    session: SessionDep,
    ctx: RequestContextDep,
    admin: AdminUser,
) -> ManagedUser:
    """Set a new password; also unlocks the account and ends its sessions."""
    return await service.reset_password(session, user_id, body.password, admin, ctx)


@router.put("/{user_id}/assignments", response_model=ManagedUser, responses=_ERRORS)
async def set_assignments(
    user_id: uuid.UUID,
    body: AssignmentsUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    admin: AdminUser,
) -> ManagedUser:
    """Replace which agents the user may prepare or review runs for."""
    return await service.set_assignments(session, user_id, body.assignments, admin, ctx)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_ERRORS,
)
async def delete_user(
    user_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> Response:
    """Only for users without runs or reviews; deactivate the others instead."""
    await service.delete_user(session, user_id, admin, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
