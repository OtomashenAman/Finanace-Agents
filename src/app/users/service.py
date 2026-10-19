"""User management for Finance Admins. Every change is audited; passwords never are."""

import uuid

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent, AgentAssignment
from src.app.agent_catalog.runs.models import AgentRun, RunReview
from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.auth.security import hash_password
from src.app.auth.service import revoke_user_tokens
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.users.exceptions import (
    EmailTakenError,
    SelfManagementError,
    UnknownAgentError,
    UserHasHistoryError,
    UserNotFoundError,
)
from src.app.users.schemas import (
    AssignmentIn,
    AssignmentOut,
    ManagedUser,
    UserCreate,
    UserUpdate,
)


async def _assignments(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AssignmentOut]]:
    rows = await session.execute(
        select(AgentAssignment.user_id, Agent.key, Agent.short_name, AgentAssignment.capacity)
        .join(Agent, Agent.id == AgentAssignment.agent_id)
        .where(AgentAssignment.user_id.in_(user_ids), Agent.retired_at.is_(None))
        .order_by(Agent.sort_order, AgentAssignment.capacity)
    )
    result: dict[uuid.UUID, list[AssignmentOut]] = {}
    for user_id, key, name, capacity in rows:
        result.setdefault(user_id, []).append(
            AssignmentOut(agent_key=key, agent_name=name, capacity=capacity)
        )
    return result


def _to_out(user: User, assignments: list[AssignmentOut]) -> ManagedUser:
    return ManagedUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        is_locked=user.locked_until is not None and user.locked_until > utcnow(),
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        assignments=assignments,
    )


async def _managed(session: AsyncSession, user: User) -> ManagedUser:
    assignments = await _assignments(session, [user.id])
    return _to_out(user, assignments.get(user.id, []))


async def _get(session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> User:
    query = select(User).where(User.id == user_id)
    user = await session.scalar(query.with_for_update() if lock else query)
    if user is None:
        raise UserNotFoundError
    return user


async def _replace_assignments(
    session: AsyncSession, user: User, wanted: list[AssignmentIn]
) -> list[str]:
    """Make the user's assignments exactly `wanted` (caller commits). Returns them as strings."""
    keys = {a.agent_key for a in wanted}
    agents = {
        a.key: a.id
        for a in await session.scalars(
            select(Agent).where(Agent.key.in_(keys), Agent.retired_at.is_(None))
        )
    }
    if missing := keys - agents.keys():
        raise UnknownAgentError(list(missing))

    await session.execute(delete(AgentAssignment).where(AgentAssignment.user_id == user.id))
    pairs = sorted({(a.agent_key, a.capacity) for a in wanted})
    session.add_all(
        AgentAssignment(user_id=user.id, agent_id=agents[key], capacity=capacity)
        for key, capacity in pairs
    )
    return [f"{key}:{capacity.value}" for key, capacity in pairs]


# --- read -------------------------------------------------------------------------------


async def list_users(session: AsyncSession, search: str | None = None) -> list[ManagedUser]:
    query = select(User).order_by(User.full_name, User.email)
    if search and (term := search.strip()):
        pattern = f"%{term}%"
        query = query.where(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
    users = list(await session.scalars(query))
    assignments = await _assignments(session, [u.id for u in users])
    return [_to_out(u, assignments.get(u.id, [])) for u in users]


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> ManagedUser:
    return await _managed(session, await _get(session, user_id))


# --- write ------------------------------------------------------------------------------


async def create_user(
    session: AsyncSession, body: UserCreate, actor: User, ctx: RequestContext
) -> ManagedUser:
    email = body.email.strip().lower()
    if await session.scalar(select(exists().where(User.email == email))):
        raise EmailTakenError
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        role=body.role,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()
    assigned = await _replace_assignments(session, user, body.assignments)
    record_event(
        session,
        "user.created",
        ctx,
        actor_id=actor.id,
        user_id=str(user.id),
        email=email,
        role=user.role.value,
        assignments=assigned,
    )
    await session.commit()
    return await _managed(session, user)


async def update_user(
    session: AsyncSession, user_id: uuid.UUID, body: UserUpdate, actor: User, ctx: RequestContext
) -> ManagedUser:
    user = await _get(session, user_id, lock=True)
    changes: dict[str, object] = {}

    if body.full_name is not None and body.full_name.strip() != user.full_name:
        user.full_name = body.full_name.strip()
        changes["full_name"] = user.full_name

    # The acting admin can never remove themselves, so an active admin always remains
    if user.id == actor.id and (
        body.is_active is False or body.role not in (None, UserRole.FINANCE_ADMIN)
    ):
        raise SelfManagementError

    if body.role is not None and body.role != user.role:
        user.role = body.role
        changes["role"] = user.role.value
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        changes["is_active"] = user.is_active
        if not user.is_active:
            await revoke_user_tokens(session, user.id)

    if changes:
        record_event(
            session, "user.updated", ctx, actor_id=actor.id, user_id=str(user.id), **changes
        )
        await session.commit()
    return await _managed(session, user)


async def reset_password(
    session: AsyncSession, user_id: uuid.UUID, password: str, actor: User, ctx: RequestContext
) -> ManagedUser:
    """Set a new password, unlock the account and sign the user out everywhere."""
    user = await _get(session, user_id, lock=True)
    user.password_hash = hash_password(password)
    user.failed_login_attempts = 0
    user.locked_until = None
    await revoke_user_tokens(session, user.id)
    record_event(session, "user.password_reset", ctx, actor_id=actor.id, user_id=str(user.id))
    await session.commit()
    return await _managed(session, user)


async def set_assignments(
    session: AsyncSession,
    user_id: uuid.UUID,
    wanted: list[AssignmentIn],
    actor: User,
    ctx: RequestContext,
) -> ManagedUser:
    user = await _get(session, user_id, lock=True)
    assigned = await _replace_assignments(session, user, wanted)
    record_event(
        session,
        "user.assignments_updated",
        ctx,
        actor_id=actor.id,
        user_id=str(user.id),
        assignments=assigned,
    )
    await session.commit()
    return await _managed(session, user)


async def delete_user(
    session: AsyncSession, user_id: uuid.UUID, actor: User, ctx: RequestContext
) -> None:
    """Hard delete, only for users with no runs or reviews (others are deactivated)."""
    user = await _get(session, user_id, lock=True)
    if user.id == actor.id:
        raise SelfManagementError
    has_history = await session.scalar(
        select(
            exists().where(AgentRun.preparer_id == user.id)
            | exists().where(RunReview.reviewer_id == user.id)
        )
    )
    if has_history:
        raise UserHasHistoryError
    record_event(
        session, "user.deleted", ctx, actor_id=actor.id, user_id=str(user.id), email=user.email
    )
    await session.delete(user)
    await session.commit()
