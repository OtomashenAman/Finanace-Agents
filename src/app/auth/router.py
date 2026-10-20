from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from src.app.auth import service
from src.app.auth.cookies import (
    SessionSlot,
    clear_auth_cookies,
    refresh_cookie,
    set_auth_cookies,
)
from src.app.auth.dependencies import CurrentUser
from src.app.auth.exceptions import InvalidRefreshTokenError
from src.app.auth.models import User
from src.app.auth.schemas import LoginRequest, PasswordChange, ResetRequest, UserOut
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
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


@router.get("/me", response_model=UserOut, responses=_UNAUTHORIZED)
async def me(user: CurrentUser) -> User:
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def change_password(
    body: PasswordChange,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    refresh_token: RefreshCookie,
) -> Response:
    """Change your own password. Your other sessions are signed out; this one stays."""
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
