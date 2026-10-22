import uuid

from fastapi import APIRouter

from src.app.approvals import service
from src.app.approvals.schemas import ApprovalItem
from src.app.auth.dependencies import CurrentUser
from src.app.core.db import SessionDep

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalItem])
async def list_approvals(
    session: SessionDep,
    user: CurrentUser,
    decided: bool = False,
    entity_id: uuid.UUID | None = None,
) -> list[ApprovalItem]:
    """Pending approvals across agents (admin: everyone's; user: their own submissions), or
    with ?decided=true the recent decisions."""
    return await service.list_approvals(session, user, decided=decided, entity_id=entity_id)
