from fastapi import Response

from src.app.core.config import get_settings

ACCESS_COOKIE = "facc_access"
REFRESH_COOKIE = "facc_refresh"
ACCESS_COOKIE_PATH = "/api"
# Refresh cookie is only ever sent to the auth endpoints
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_ttl_minutes * 60,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    for name, path in ((ACCESS_COOKIE, ACCESS_COOKIE_PATH), (REFRESH_COOKIE, REFRESH_COOKIE_PATH)):
        response.delete_cookie(
            name, path=path, httponly=True, secure=settings.cookie_secure, samesite="lax"
        )
