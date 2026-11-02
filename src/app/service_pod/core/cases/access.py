"""Loading a case by id, shared by the case, messaging and posting task services.

Pass the caller's access and a case of another POD, or one this person may not see, is
"not found": the Service POD never serves a Finance POD case and the reverse.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.exceptions import CaseNotFoundError, StaleVersionError
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.workflows import WORKFLOWS


def can_see(access: PodAccess, case: PodCase) -> bool:
    """A Finance Admin sees every case of the POD; anyone else the cases they opened, plus
    every case of a workflow whose viewer capacity they hold for its entity."""
    spec = WORKFLOWS[case.workflow]
    if spec.pod != access.pod:
        return False
    return (
        access.is_admin
        or case.owner_id == access.user.id
        or access.holds_any(set(spec.plan.viewers) & set(access.capacities), case.entity_id)
    )


async def load_case(
    session: AsyncSession,
    case_id: uuid.UUID,
    *,
    lock: bool = False,
    expected_version: int | None = None,
    access: PodAccess | None = None,
) -> PodCase:
    query = select(PodCase).where(PodCase.id == case_id)
    if lock:
        query = query.with_for_update()
    case = await session.scalar(query)
    if case is None or (access is not None and not can_see(access, case)):
        raise CaseNotFoundError
    if expected_version is not None and case.version != expected_version:
        raise StaleVersionError
    return case
