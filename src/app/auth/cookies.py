import re
from typing import Annotated

from fastapi import Depends, Request, Response

from src.app.core.config import get_settings

ACCESS_COOKIE = "facc_access"
REFRESH_COOKIE = "facc_refresh"
ACCESS_COOKIE_PATH = "/api"
# Refresh cookie is only ever sent to the auth endpoints
REFRESH_COOKIE_PATH = "/api/v1/auth"

# Each browser tab may hold its own session (e.g. an admin and a user side by side): the SPA
# sends its tab's slot id in this header and the cookies carry the slot in their name. They
# stay httpOnly; without the header the plain cookie names are used.
SLOT_HEADER = "X-Session-Slot"
_SLOT = re.compile(r"[a-z0-9]{8,32}")


def session_slot(request: Request) -> str | None:
    slot = request.headers.get(SLOT_HEADER, "").lower()
    return slot if _SLOT.fullmatch(slot) else None


SessionSlot = Annotated[str | None, Depends(session_slot)]


def access_cookie(slot: str | None) -> str:
    return f"{ACCESS_COOKIE}_{slot}" if slot else ACCESS_COOKIE


def refresh_cookie(slot: str | None) -> str:
    return f"{REFRESH_COOKIE}_{slot}" if slot else REFRESH_COOKIE


def set_auth_cookies(
    response: Response, access_token: str, refresh_token: str, slot: str | None = None
) -> None:
    settings = get_settings()
    response.set_cookie(
        access_cookie(slot),
        access_token,
        max_age=settings.access_token_ttl_minutes * 60,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        refresh_cookie(slot),
        refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_auth_cookies(response: Response, slot: str | None = None) -> None:
    settings = get_settings()
    for name, path in (
        (access_cookie(slot), ACCESS_COOKIE_PATH),
        (refresh_cookie(slot), REFRESH_COOKIE_PATH),
    ):
        response.delete_cookie(
            name, path=path, httponly=True, secure=settings.cookie_secure, samesite="lax"
        )
