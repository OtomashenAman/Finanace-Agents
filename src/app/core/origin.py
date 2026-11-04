"""CSRF defence in depth: state-changing requests must come from the app's own origin.

SameSite=Strict cookies already keep other sites' requests unauthenticated; this check also
rejects them when a browser doesn't honour SameSite. Browsers always send Origin on
POST/PUT/PATCH/DELETE (and Sec-Fetch-Site), and a page can't forge either. Clients that send
neither (curl, scripts, tests) are not browsers, so CSRF doesn't apply to them.
"""

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.app.core.config import Settings, get_settings
from src.app.core.errors import AppError, app_error_response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class CrossOriginRequestError(AppError):
    status_code = 403
    code = "cross_origin_request"
    message = "This request did not come from the application and was refused."


def _origin(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def allowed_origins(settings: Settings) -> frozenset[str]:
    urls = [settings.public_base_url, *settings.cors_origins]
    return frozenset(o for o in (_origin(u) for u in urls) if o is not None)


def origin_allowed(origin: str, settings: Settings) -> bool:
    normalized = _origin(origin)
    if normalized is None:  # "null" (sandboxed iframes, file://) or garbage
        return False
    if normalized in allowed_origins(settings):
        return True
    # Local development: any port on this machine (Vite on 8081, a second dev server, ...)
    return not settings.is_production and urlsplit(normalized).hostname in _LOCAL_HOSTS


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                if not origin_allowed(origin, get_settings()):
                    return app_error_response(CrossOriginRequestError())
            elif request.headers.get("sec-fetch-site") == "cross-site":
                return app_error_response(CrossOriginRequestError())
        return await call_next(request)
