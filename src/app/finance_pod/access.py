"""Who gets into the Finance POD: a Finance Admin (every capacity, every entity), or anyone
a Finance Admin granted at least one capacity. Segregation of duties is checked per step and
sign-off, for admins too."""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.dependencies import CurrentUser
from src.app.auth.exceptions import PermissionDeniedError
from src.app.auth.models import User, UserRole
from src.app.core.db import SessionDep
from src.app.finance_pod.models import FinanceCapacityAssignment
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.workflows import PodKey


async def capacities_of(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, frozenset[uuid.UUID] | None]:
    """capacity -> the entities it is held for (None: all entities)."""
    rows = await session.scalars(
        select(FinanceCapacityAssignment).where(FinanceCapacityAssignment.user_id == user_id)
    )
    held: dict[str, set[uuid.UUID] | None] = {}
    for row in rows:
        current = held.get(row.capacity.value, set())
        if row.entity_id is None or current is None:
            held[row.capacity.value] = None
        else:
            current.add(row.entity_id)
            held[row.capacity.value] = current
    return {cap: None if ents is None else frozenset(ents) for cap, ents in held.items()}


async def finance_access(session: AsyncSession, user: User) -> PodAccess:
    if user.role == UserRole.FINANCE_ADMIN:
        return PodAccess(user=user, pod=PodKey.FINANCE)
    capacities = await capacities_of(session, user.id)
    if not capacities:
        raise PermissionDeniedError
    return PodAccess(user=user, pod=PodKey.FINANCE, capacities=capacities)


async def get_finance_access(session: SessionDep, user: CurrentUser) -> PodAccess:
    """403 for anyone without a Finance POD capacity."""
    return await finance_access(session, user)


FinanceAccessDep = Annotated[PodAccess, Depends(get_finance_access)]
