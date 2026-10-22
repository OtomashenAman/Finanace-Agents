from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request


@dataclass(frozen=True)
class RequestContext:
    """Who/where a request came from, for audit records."""

    ip: str | None
    user_agent: str | None


def get_request_context(request: Request) -> RequestContext:
    # Behind nginx, uvicorn --proxy-headers puts the real client IP in request.client
    return RequestContext(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]
