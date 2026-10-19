from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Response, status

from src.app.auth import service
from src.app.auth.cookies import REFRESH_COOKIE, clear_auth_cookies, set_auth_cookies
from src.app.auth.dependencies import CurrentUser
from src.app.auth.exceptions import InvalidRefreshTokenError
from src.app.auth.models import User
from src.app.auth.schemas import LoginRequest, UserOut
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.core.errors import app_error_response

router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]
_UNAUTHORIZED: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse}}


@router.post(
    "/login",
    response_model=UserOut,
    responses={**_UNAUTHORIZED, 423: {"model": ErrorResponse}},
)
async def login(
    body: LoginRequest, response: Response, session: SessionDep, ctx: RequestContextDep
) -> User:
    user = await service.authenticate(session, body.email, body.password, ctx)
    tokens = service.issue_tokens(session, user, ctx)
    await session.commit()
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return user


@router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_UNAUTHORIZED,
)
async def refresh(
    session: SessionDep, ctx: RequestContextDep, refresh_token: RefreshCookie = None
) -> Response:
    try:
        if not refresh_token:
            raise InvalidRefreshTokenError
        _, tokens = await service.rotate_refresh_token(session, refresh_token, ctx)
    except InvalidRefreshTokenError as exc:
        error = app_error_response(exc)
        clear_auth_cookies(error)
        return error
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(
    session: SessionDep, ctx: RequestContextDep, refresh_token: RefreshCookie = None
) -> Response:
    await service.logout(session, refresh_token, ctx)
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserOut, responses=_UNAUTHORIZED)
async def me(user: CurrentUser) -> User:
    return user
