"""Who may use the Service POD: the Finance Admin, and nobody else.

One person runs every step and approves their own work. What keeps it right are the checks
that need no second person: figures locked to the source, approvals bound to a content
fingerprint, dates only from the customer, and every manual posting verified against a
fresh export.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from src.app.auth.dependencies import AdminUser
from src.app.auth.exceptions import PermissionDeniedError
from src.app.auth.models import Area, User
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.workflows import WORKFLOWS


@dataclass(frozen=True)
class PodAccess:
    user: User


async def get_pod_access(user: AdminUser) -> PodAccess:
    """403 for anyone but a Finance Admin (AdminUser refuses them) given the Service POD."""
    if not user.can_use(Area.SERVICE_POD):
        raise PermissionDeniedError
    return PodAccess(user=user)


PodAccessDep = Annotated[PodAccess, Depends(get_pod_access)]


def workflows_for() -> list[WorkflowOut]:
    return [
        WorkflowOut(
            key=spec.key,
            name=spec.name,
            prefix=spec.prefix,
            description=spec.description,
            required=sorted(spec.required),
            signoff_as=spec.signoff_as,
            signoffs=list(spec.signoffs),
        )
        for spec in WORKFLOWS.values()
    ]
