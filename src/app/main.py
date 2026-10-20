import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.app.core.config import get_settings
from src.app.core.db import SessionDep, get_engine
from src.app.core.errors import register_exception_handlers
from src.app.core.observability import ObservabilityMiddleware, http_metrics, setup_logging
from src.app.monitoring.metrics import business_metrics
from src.app.router import api_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    # API docs only outside production
    docs = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    # The SPA is served same-origin (Vite proxy / nginx), so CORS is only for extra origins
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(ObservabilityMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/")
    def read_root() -> dict[str, str]:
        return {"message": "FinanceACC API is running"}

    @app.get("/health")
    def health_check() -> dict[str, str]:
        """Liveness: the process answers."""
        return {"status": "ok"}

    @app.get("/ready", response_model=None)
    async def ready(session: SessionDep) -> dict[str, str] | JSONResponse:
        """Readiness: the database answers too (load balancers route on this)."""
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "unavailable", "database": "down"}, status_code=503)
        return {"status": "ready", "database": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request, session: SessionDep) -> Response:
        """Prometheus scrape target (Bearer METRICS_TOKEN; closed in production without one)."""
        token = settings.metrics_token
        if token is None and settings.is_production:
            return Response(status_code=404)
        if token is not None:
            sent = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(sent, token.get_secret_value()):
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        body = "\n".join([*http_metrics(), *await business_metrics(session)]) + "\n"
        return Response(body, media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


app = create_app()
