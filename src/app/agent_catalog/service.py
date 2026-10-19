import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.exceptions import AgentNotFoundError
from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.registry import REGISTRY, get_agent_definition
from src.app.agent_catalog.schemas import AgentOut
from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext

# Columns the code registry owns; everything else (is_active, assignments) belongs to admins
_CODE_OWNED = ("code", "name", "short_name", "description", "primary_user", "reviewer")


@dataclass
class SyncResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


async def sync_registry(session: AsyncSession) -> SyncResult:
    """Upsert registry definitions into `agents` (caller commits). Never deletes rows."""
    result = SyncResult()
    existing = {agent.key: agent for agent in await session.scalars(select(Agent))}

    for key, definition in REGISTRY.items():
        values: dict[str, object] = {f: getattr(definition, f) for f in _CODE_OWNED}
        values["sort_order"] = definition.sort_order()
        agent = existing.get(key)
        if agent is None:
            session.add(Agent(key=key, **values))
            result.created.append(key)
            continue
        changed = agent.retired_at is not None or any(
            getattr(agent, f) != v for f, v in values.items()
        )
        for f, v in values.items():
            setattr(agent, f, v)
        agent.retired_at = None  # back in the registry
        if changed:
            result.updated.append(key)

    for key, agent in existing.items():
        if key not in REGISTRY and agent.retired_at is None:
            agent.retired_at = utcnow()
            result.retired.append(key)
    return result


def _visible_agents(user: User) -> Select[Agent]:
    """Finance Admin sees every registered agent; others only active agents assigned to them."""
    query = select(Agent).where(Agent.retired_at.is_(None))
    if user.role != UserRole.FINANCE_ADMIN:
        assigned = select(AgentAssignment.agent_id).where(AgentAssignment.user_id == user.id)
        query = query.where(Agent.is_active.is_(True), Agent.id.in_(assigned))
    return query


def visible_agent_ids(user: User) -> Select[tuple[uuid.UUID]]:
    """Ids of agents the user may see (for filtering other features' data)."""
    return select(_visible_agents(user).subquery().c.id)


async def _capacities(session: AsyncSession, user: User) -> dict[uuid.UUID, list[AgentCapacity]]:
    rows = await session.execute(
        select(AgentAssignment.agent_id, AgentAssignment.capacity).where(
            AgentAssignment.user_id == user.id
        )
    )
    capacities: dict[uuid.UUID, list[AgentCapacity]] = {}
    for agent_id, capacity in rows:
        capacities.setdefault(agent_id, []).append(capacity)
    return capacities


def _has_workspace(key: str) -> bool:
    definition = get_agent_definition(key)
    return definition is not None and definition.has_workspace()


def _to_out(agent: Agent, capacities: list[AgentCapacity]) -> AgentOut:
    return AgentOut(
        key=agent.key,
        code=agent.code,
        name=agent.name,
        short_name=agent.short_name,
        description=agent.description,
        primary_user=agent.primary_user,
        reviewer=agent.reviewer,
        is_active=agent.is_active,
        has_workspace=_has_workspace(agent.key),
        my_capacities=sorted(capacities),
    )


async def list_agents(session: AsyncSession, user: User) -> list[AgentOut]:
    agents = await session.scalars(_visible_agents(user).order_by(Agent.sort_order))
    capacities = await _capacities(session, user)
    return [_to_out(agent, capacities.get(agent.id, [])) for agent in agents]


async def get_agent(session: AsyncSession, user: User, key: str) -> AgentOut:
    agent = await session.scalar(_visible_agents(user).where(Agent.key == key))
    if agent is None:
        raise AgentNotFoundError
    capacities = await _capacities(session, user)
    return _to_out(agent, capacities.get(agent.id, []))


async def count_active_agents(session: AsyncSession, user: User) -> int:
    visible = _visible_agents(user).where(Agent.is_active.is_(True)).subquery()
    return await session.scalar(select(func.count()).select_from(visible)) or 0


async def set_agent_active(
    session: AsyncSession, key: str, is_active: bool, actor: User, ctx: RequestContext
) -> AgentOut:
    """Enable/disable an agent for everyone (caller commits)."""
    agent = await session.scalar(
        select(Agent).where(Agent.key == key, Agent.retired_at.is_(None)).with_for_update()
    )
    if agent is None:
        raise AgentNotFoundError
    if agent.is_active != is_active:
        agent.is_active = is_active
        event = "agent.activated" if is_active else "agent.deactivated"
        record_event(session, event, ctx, actor_id=actor.id, agent_key=key)
    return _to_out(agent, [])
