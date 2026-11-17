"""Loading a case by id, shared by the case, messaging and posting task services."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.access.service import current_access
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
    access = current_access()
    # A case outside the person's workflows is reported as missing, never shown
    if case is None or (
        access is not None
        and not (access.allows(case.workflow) and access.allows_entity(case.entity_id))
    ):
        raise CaseNotFoundError
    if expected_version is not None and case.version != expected_version:
        raise StaleVersionError
    return case
