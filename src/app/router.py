from fastapi import APIRouter

from src.app.agent_catalog.router import router as agent_catalog_router
from src.app.agent_catalog.runs.router import router as agent_runs_router
from src.app.auth.router import router as auth_router
from src.app.data_sources.router import admin_router as data_sources_admin_router
from src.app.data_sources.router import router as data_sources_router
from src.app.overview.router import router as overview_router
from src.app.users.router import router as users_router

# Every feature router is registered here; main.py mounts this under /api/v1
api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(agent_catalog_router)
api_router.include_router(agent_runs_router)
api_router.include_router(overview_router)
api_router.include_router(users_router)
api_router.include_router(data_sources_router)
api_router.include_router(data_sources_admin_router)
