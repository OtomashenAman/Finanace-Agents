import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User

DELETED = "a deleted user"


async def names(session: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
    return dict(rows.all())


def name_of(lookup: dict[uuid.UUID, str], user_id: uuid.UUID | None) -> str | None:
    return None if user_id is None else lookup.get(user_id, DELETED)
