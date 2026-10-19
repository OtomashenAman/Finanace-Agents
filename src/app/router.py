from fastapi import APIRouter

from src.app.auth.router import router as auth_router

# Every feature router is registered here; main.py mounts this under /api/v1
api_router = APIRouter()
api_router.include_router(auth_router)
