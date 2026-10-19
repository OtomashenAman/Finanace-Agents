import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

import jwt
from fastapi import Cookie, Depends

from src.app.auth.cookies import ACCESS_COOKIE
from src.app.auth.exceptions import NotAuthenticatedError, PermissionDeniedError, TokenExpiredError
from src.app.auth.models import User, UserRole
from src.app.auth.security import decode_access_token
from src.app.core.db import SessionDep


async def get_current_user(
    session: SessionDep,
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> User:
    if not access_token:
        raise NotAuthenticatedError
    try:
        payload = decode_access_token(access_token)
        user_id = uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise NotAuthenticatedError from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: `Depends(require_roles(UserRole.FINANCE_ADMIN))`."""

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError
        return user

    return checker
