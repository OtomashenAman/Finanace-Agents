"""Legal entities and who works for which.

Scoping switches on when the first entity is created: from then on every new run names an
entity the preparer is assigned to, and users only see runs of their entities. Finance
Admins work across all entities.
"""

import uuid

from sqlalchemy import Select, delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext
from src.app.entities.exceptions import (
    EntityCodeTakenError,
    EntityNotAllowedError,
    EntityNotFoundError,
    EntityRequiredError,
    NoEntitiesAssignedError,
)
from src.app.entities.models import EntityAssignment, LegalEntity
from src.app.entities.schemas import EntityCreate, EntityOut, EntityRef, EntityUpdate


def _is_admin(user: User) -> bool:
    return user.role == UserRole.FINANCE_ADMIN


def assigned_entity_ids(user_id: uuid.UUID) -> Select[uuid.UUID]:
    return select(EntityAssignment.entity_id).where(EntityAssignment.user_id == user_id)


async def scoping_enabled(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(exists().select_from(LegalEntity))))


# --- read -------------------------------------------------------------------------------


async def list_entities(session: AsyncSession, viewer: User) -> list[EntityOut]:
    """Admins: every entity. Users: the ones they are assigned to."""
    query = select(LegalEntity).order_by(LegalEntity.code)
    if not _is_admin(viewer):
        query = query.where(LegalEntity.id.in_(assigned_entity_ids(viewer.id)))
    return [EntityOut.model_validate(e) for e in await session.scalars(query)]


async def visible_entity(session: AsyncSession, viewer: User, entity_id: uuid.UUID) -> EntityRef:
    """An entity the viewer may filter by (admins: any; users: their own)."""
    query = select(LegalEntity).where(LegalEntity.id == entity_id)
    if not _is_admin(viewer):
        query = query.where(LegalEntity.id.in_(assigned_entity_ids(viewer.id)))
    entity = await session.scalar(query)
    if entity is None:
        raise EntityNotFoundError
    return EntityRef(id=entity.id, code=entity.code, name=entity.name)


async def refs(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, EntityRef]:
    if not ids:
        return {}
    rows = await session.scalars(select(LegalEntity).where(LegalEntity.id.in_(ids)))
    return {e.id: EntityRef(id=e.id, code=e.code, name=e.name) for e in rows}


async def entities_of(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[EntityRef]]:
    rows = await session.execute(
        select(EntityAssignment.user_id, LegalEntity)
        .join(LegalEntity, LegalEntity.id == EntityAssignment.entity_id)
        .where(EntityAssignment.user_id.in_(user_ids))
        .order_by(LegalEntity.code)
    )
    result: dict[uuid.UUID, list[EntityRef]] = {}
    for user_id, entity in rows:
        result.setdefault(user_id, []).append(
            EntityRef(id=entity.id, code=entity.code, name=entity.name)
        )
    return result


# --- runs -------------------------------------------------------------------------------


async def entity_for_new_run(
    session: AsyncSession, user: User, entity_id: uuid.UUID | None
) -> LegalEntity | None:
    """The entity a new run is filed for. None while no entities exist (scoping off).

    Without an explicit choice, a user with exactly one active entity gets that one.
    """
    if not await scoping_enabled(session):
        return None
    candidates = select(LegalEntity).where(LegalEntity.is_active.is_(True))
    if not _is_admin(user):
        candidates = candidates.where(LegalEntity.id.in_(assigned_entity_ids(user.id)))
    if entity_id is not None:
        entity = await session.scalar(candidates.where(LegalEntity.id == entity_id))
        if entity is None:
            raise EntityNotAllowedError
        return entity
    options = list(await session.scalars(candidates.limit(2)))
    if not options:
        raise NoEntitiesAssignedError if not _is_admin(user) else EntityRequiredError
    if len(options) > 1:
        raise EntityRequiredError
    return options[0]


# --- write (Finance Admin) --------------------------------------------------------------


async def _get(session: AsyncSession, entity_id: uuid.UUID) -> LegalEntity:
    entity = await session.get(LegalEntity, entity_id, with_for_update=True)
    if entity is None:
        raise EntityNotFoundError
    return entity


async def create_entity(
    session: AsyncSession, body: EntityCreate, actor: User, ctx: RequestContext
) -> EntityOut:
    code = body.code.strip().upper()
    if await session.scalar(select(exists().where(LegalEntity.code == code))):
        raise EntityCodeTakenError
    entity = LegalEntity(code=code, name=body.name.strip())
    session.add(entity)
    await session.flush()
    record_event(
        session,
        "entity.created",
        ctx,
        actor_id=actor.id,
        entity_id=str(entity.id),
        code=code,
        name=entity.name,
    )
    await session.commit()
    return EntityOut.model_validate(entity)


async def update_entity(
    session: AsyncSession,
    entity_id: uuid.UUID,
    body: EntityUpdate,
    actor: User,
    ctx: RequestContext,
) -> EntityOut:
    entity = await _get(session, entity_id)
    changes: dict[str, object] = {}
    if body.name is not None and body.name.strip() != entity.name:
        entity.name = changes["name"] = body.name.strip()
    if body.is_active is not None and body.is_active != entity.is_active:
        entity.is_active = changes["is_active"] = body.is_active
    if changes:
        record_event(
            session,
            "entity.updated",
            ctx,
            actor_id=actor.id,
            entity_id=str(entity.id),
            code=entity.code,
            **changes,
        )
        await session.commit()
    return EntityOut.model_validate(entity)


async def set_user_entities(
    session: AsyncSession, user: User, entity_ids: list[uuid.UUID]
) -> list[str]:
    """Make the user's entities exactly `entity_ids` (caller audits and commits)."""
    wanted = set(entity_ids)
    found = {
        e.id: e.code
        for e in await session.scalars(select(LegalEntity).where(LegalEntity.id.in_(wanted)))
    }
    if wanted - found.keys():
        raise EntityNotFoundError
    await session.execute(delete(EntityAssignment).where(EntityAssignment.user_id == user.id))
    session.add_all(EntityAssignment(user_id=user.id, entity_id=i) for i in wanted)
    return sorted(found.values())
