from fastapi import APIRouter

from src.app.auth.dependencies import CurrentUser
from src.app.core.db import SessionDep
from src.app.worklist import service
from src.app.worklist.schemas import Worklist

router = APIRouter(prefix="/worklist", tags=["worklist"])


@router.get("", response_model=Worklist)
async def get_worklist(session: SessionDep, user: CurrentUser) -> Worklist:
    """What needs you now (most urgent first), what waits on others, and (admins) what to know."""
    return await service.get_worklist(session, user)
