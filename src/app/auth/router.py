import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from src.app.auth import service
from src.app.auth.cookies import (
    SessionSlot,
    clear_auth_cookies,
    refresh_cookie,
    set_auth_cookies,
)
from src.app.auth.dependencies import AdminUser, CurrentUser
from src.app.auth.exceptions import InvalidRefreshTokenError, PermissionDeniedError
from src.app.auth.models import User, UserRole
from src.app.auth.schemas import (
    ActAsRequest,
    ActingAdmin,
    LoginRequest,
    MeOut,
    PasswordChange,
    ResetRequest,
    UserOut,
)
from src.app.auth.service import ActAsRefusedError
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.errors import app_error_response

router = APIRouter(prefix="/auth", tags=["auth"])


def _refresh_token(request: Request, slot: SessionSlot) -> str | None:
    return request.cookies.get(refresh_cookie(slot))


RefreshCookie = Annotated[str | None, Depends(_refresh_token)]
_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse}}


@router.post(
    "/login",
    response_model=UserOut,
    responses={**_UNAUTHORIZED, 423: {"model": ErrorResponse}},
)
async def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    ctx: RequestContextDep,
    slot: SessionSlot,
) -> User:
    user = await service.authenticate(session, body.email, body.password, ctx)
    tokens = service.issue_tokens(session, user, ctx)
    await session.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token, slot)
    return user


@router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_UNAUTHORIZED,
)
async def refresh(
    session: SessionDep, ctx: RequestContextDep, slot: SessionSlot, refresh_token: RefreshCookie
) -> Response:
    try:
        if not refresh_token:
            raise InvalidRefreshTokenError
        _, tokens = await service.rotate_refresh_token(session, refresh_token, ctx)
    except InvalidRefreshTokenError as exc:
        error = app_error_response(exc)
        clear_auth_cookies(error, slot)
        return error
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token, slot)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(
    session: SessionDep, ctx: RequestContextDep, slot: SessionSlot, refresh_token: RefreshCookie
) -> Response:
    await service.logout(session, refresh_token, ctx)
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response, slot)
    return response


@router.get("/me", response_model=MeOut, responses=_UNAUTHORIZED)
async def me(user: CurrentUser, request: Request, session: SessionDep) -> MeOut:
    out = MeOut.model_validate(user, from_attributes=True)
    if acted_by := getattr(request.state, "acted_by", None):
        admin = await session.get(User, uuid.UUID(acted_by))
        if admin is not None:
            out.acted_by = ActingAdmin(id=admin.id, full_name=admin.full_name, email=admin.email)
    out.can_act_as = user.role == UserRole.FINANCE_ADMIN and get_settings().act_as_enabled
    return out


@router.post(
    "/act-as",
    response_model=UserOut,
    responses={**_UNAUTHORIZED, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def act_as(
    body: ActAsRequest,
    response: Response,
    session: SessionDep,
    admin: AdminUser,
    ctx: RequestContextDep,
    slot: SessionSlot,
) -> User:
    """A Finance Admin (signed in in this tab) opens a session as another user in a new tab
    (`slot`: that tab's session slot), to do their step while testing a workflow. Dev and demo
    only (ACT_AS_ALLOWED); audited, and every event in it says it was the admin."""
    if body.slot == slot:
        raise ActAsRefusedError("Open the user in a new tab, not this one.")
    target, tokens = await service.act_as(session, admin, body.user_id, ctx)
    await session.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token, body.slot)
    return target


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def change_password(
    request: Request,
    body: PasswordChange,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    refresh_token: RefreshCookie,
) -> Response:
    """Change your own password. Your other sessions are signed out; this one stays."""
    if getattr(request.state, "acted_by", None):
        raise PermissionDeniedError(
            "A Finance Admin testing as this user can't change their password."
        )
    await service.change_password(
        session, user, body.current_password, body.new_password, refresh_token, ctx
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset-requests", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    body: ResetRequest, session: SessionDep, ctx: RequestContextDep
) -> dict[str, str]:
    """Forgot password: a Finance Admin is asked to set a new one (no email is sent)."""
    await service.request_reset(session, body.email, ctx)
    return {"message": "If that account exists, a Finance Admin has been asked to reset it."}
