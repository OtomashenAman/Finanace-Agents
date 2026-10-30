"""Loading a case for someone who may see it, and their part in it. Shared by the case,
messaging and posting task services."""

import uuid
from enum import StrEnum

from sqlalchemy import ColumnElement, and_, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.exceptions import CaseNotFoundError, StaleVersionError
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.workflows import Capacity


class CaseRole(StrEnum):
    OWNER = "owner"
    REVIEWER = "reviewer"
    FINAL_APPROVER = "final_approver"


def roles_on(case: PodCase, access: PodAccess) -> set[CaseRole]:
    """The viewer's part in this case. Reviewers act only on other people's cases."""
    if not access.can_see_entity(case.entity_id):
        return set()
    roles = set()
    if case.owner_id == access.user.id and access.has(case.workflow, Capacity.PREPARER):
        roles.add(CaseRole.OWNER)
    if case.owner_id != access.user.id:
        if access.has(case.workflow, Capacity.REVIEWER):
            roles.add(CaseRole.REVIEWER)
        if access.has(case.workflow, Capacity.FINAL_APPROVER):
            roles.add(CaseRole.FINAL_APPROVER)
    return roles


def can_view(case: PodCase, access: PodAccess) -> bool:
    if access.is_admin:
        return True
    if not access.can_see_entity(case.entity_id):
        return False
    return case.owner_id == access.user.id or bool(roles_on(case, access))


def visible_cases_clause(access: PodAccess) -> ColumnElement[bool]:
    """SQL version of can_view, for lists."""
    if access.is_admin:
        return true()
    reviewing = [
        w
        for w, caps in access.capacities.items()
        if caps & {Capacity.REVIEWER, Capacity.FINAL_APPROVER}
    ]
    entity_ids = access.entity_ids or frozenset()
    if not entity_ids:
        return false()
    return and_(
        PodCase.entity_id.in_(entity_ids),
        or_(PodCase.owner_id == access.user.id, PodCase.workflow.in_(reviewing)),
    )


async def load_case(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    *,
    lock: bool = False,
    expected_version: int | None = None,
) -> PodCase:
    query = select(PodCase).where(PodCase.id == case_id)
    if lock:
        query = query.with_for_update()
    case = await session.scalar(query)
    if case is None or not can_view(case, access):
        raise CaseNotFoundError
    if expected_version is not None and case.version != expected_version:
        raise StaleVersionError
    return case
