"""Who may use the Finance POD (Finance Admins) and the separation-of-duties check.

Every decision records the capacity it was given in (budget owner, buyer, AP analyst...).
Two capacities that must be different people, such as requester and budget owner, are
checked between admin accounts. With `allow_self_approval` on (a single-admin demo), the
same person may act in both, and the audit event says so.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.dependencies import AdminUser
from src.app.auth.exceptions import PermissionDeniedError
from src.app.auth.models import Area, User, UserRole
from src.app.core.errors import AppError
from src.app.finance_pod.settings.service import current


class SeparationOfDutiesError(AppError):
    status_code = 403
    code = "separation_of_duties"


@dataclass(frozen=True)
class FinanceAccess:
    user: User


async def get_finance_access(user: AdminUser) -> FinanceAccess:
    """403 for anyone but a Finance Admin (AdminUser refuses them) given the Finance POD."""
    if not user.can_use(Area.FINANCE_POD):
        raise PermissionDeniedError
    return FinanceAccess(user=user)


def finance_pod_people() -> ColumnElement[bool]:
    """Who can act in the Finance POD (approvers, owners, second persons): active Finance
    Admins given the Finance POD."""
    return (
        (User.role == UserRole.FINANCE_ADMIN)
        & User.is_active
        & User.areas.contains([Area.FINANCE_POD.value])
    )


FinanceAccessDep = Annotated[FinanceAccess, Depends(get_finance_access)]


async def check_different_person(
    session: AsyncSession, actor: User, earlier_id: uuid.UUID | None, rule: str
) -> bool:
    """Refuse `actor` when they are `earlier_id` (e.g. the requester), unless the settings
    allow self-approval. Returns True when the rule was overridden, for the audit event."""
    if earlier_id is None or earlier_id != actor.id:
        return False
    if (await current(session)).allow_self_approval:
        return True
    raise SeparationOfDutiesError(
        f"{rule} A different Finance Admin has to do this step "
        "(or turn on self-approval in the Finance POD settings for a single-admin setup)."
    )
