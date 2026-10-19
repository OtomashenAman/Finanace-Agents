from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.app.agent_catalog import service
from src.app.agent_catalog.schemas import AgentOut, AgentUpdate
from src.app.auth.dependencies import CurrentUser, require_roles
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep

router = APIRouter(prefix="/agents", tags=["agent catalog"])

FinanceAdmin = Annotated[User, Depends(require_roles(UserRole.FINANCE_ADMIN))]
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.get("", response_model=list[AgentOut])
async def list_agents(session: SessionDep, user: CurrentUser) -> list[AgentOut]:
    """Agents the current user can see, in catalog order."""
    return await service.list_agents(session, user)


@router.get("/{key}", response_model=AgentOut, responses=_NOT_FOUND)
async def get_agent(key: str, session: SessionDep, user: CurrentUser) -> AgentOut:
    return await service.get_agent(session, user, key)


@router.patch(
    "/{key}",
    response_model=AgentOut,
    responses={**_NOT_FOUND, 403: {"model": ErrorResponse}},
)
async def update_agent(
    key: str, body: AgentUpdate, session: SessionDep, ctx: RequestContextDep, admin: FinanceAdmin
) -> AgentOut:
    """Enable or disable an agent (Finance Admin only)."""
    agent = await service.set_agent_active(session, key, body.is_active, admin, ctx)
    await session.commit()
    return agent
