from fastapi import APIRouter

from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.core.dashboard import service
from src.app.service_pod.core.dashboard.schemas import Dashboard

router = APIRouter(tags=["service pod: dashboard"])


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(session: SessionDep, access: PodAccessDep) -> Dashboard:
    """Cases by stage, payment promises, aging and mail health across the Service POD."""
    return await service.dashboard(session, access)
