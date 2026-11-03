from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request


@dataclass(frozen=True)
class RequestContext:
    """Who/where a request came from, for audit records."""

    ip: str | None
    user_agent: str | None
    # The Finance Admin acting as the signed-in user (testing a workflow), if any
    acted_by: str | None = None


def _acted_by(request: Request) -> str | None:
    """The "act" claim of this tab's session, read without failing the request (the auth
    dependency rejects a bad token itself)."""
    from src.app.auth.cookies import access_cookie, session_slot
    from src.app.auth.security import decode_access_token

    token = request.cookies.get(access_cookie(session_slot(request)))
    if not token:
        return None
    try:
        act = decode_access_token(token).get("act")
    except Exception:
        return None
    return act if isinstance(act, str) else None


def get_request_context(request: Request) -> RequestContext:
    # Behind nginx, uvicorn --proxy-headers puts the real client IP in request.client
    return RequestContext(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        acted_by=_acted_by(request),
    )


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]
