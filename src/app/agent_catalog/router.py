from typing import Any

from fastapi import APIRouter

from src.app.agent_catalog import service
from src.app.agent_catalog.schemas import AgentOut, AgentUpdate
from src.app.auth.dependencies import AdminUser, CurrentUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep

router = APIRouter(prefix="/agents", tags=["agent catalog"])

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
    key: str, body: AgentUpdate, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> AgentOut:
    """Enable or disable an agent (Finance Admin only)."""
    agent = await service.set_agent_active(session, key, body.is_active, admin, ctx)
    await session.commit()
    return agent
