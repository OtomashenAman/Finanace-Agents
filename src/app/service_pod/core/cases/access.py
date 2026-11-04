"""Loading a case by id, shared by the case, messaging and posting task services."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.cases.exceptions import CaseNotFoundError, StaleVersionError
from src.app.service_pod.core.cases.models import PodCase


async def load_case(
    session: AsyncSession,
    case_id: uuid.UUID,
    *,
    lock: bool = False,
    expected_version: int | None = None,
) -> PodCase:
    query = select(PodCase).where(PodCase.id == case_id)
    if lock:
        query = query.with_for_update()
    case = await session.scalar(query)
    if case is None:
        raise CaseNotFoundError
    if expected_version is not None and case.version != expected_version:
        raise StaleVersionError
    return case
