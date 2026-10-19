from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.core.config import get_settings
from src.app.core.db import get_engine
from src.app.core.errors import register_exception_handlers
from src.app.router import api_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
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

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/")
    def read_root() -> dict[str, str]:
        return {"message": "FinanceACC API is running"}

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
