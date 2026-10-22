import uuid
from typing import Any

from fastapi import APIRouter, status

from src.app.auth.dependencies import AdminUser, CurrentUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.entities import service
from src.app.entities.schemas import EntityCreate, EntityOut, EntityUpdate

router = APIRouter(prefix="/entities", tags=["legal entities"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409)
}


@router.get("", response_model=list[EntityOut])
async def list_entities(session: SessionDep, user: CurrentUser) -> list[EntityOut]:
    """Finance Admin: every entity. User: the entities they work for."""
    return await service.list_entities(session, user)


@router.post("", response_model=EntityOut, status_code=status.HTTP_201_CREATED, responses=_ERRORS)
async def create_entity(
    body: EntityCreate, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> EntityOut:
    """The first entity switches on entity scoping for new runs."""
    return await service.create_entity(session, body, admin, ctx)


@router.patch("/{entity_id}", response_model=EntityOut, responses=_ERRORS)
async def update_entity(
    entity_id: uuid.UUID,
    body: EntityUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    admin: AdminUser,
) -> EntityOut:
    """Rename or (de)activate. Deactivated entities keep their runs but take no new ones."""
    return await service.update_entity(session, entity_id, body, admin, ctx)
