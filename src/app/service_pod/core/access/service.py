"""Who may use a POD.

Service POD: the Finance Admin, and nobody else. One person runs every step and approves
their own work. What keeps it right are the checks that need no second person: figures
locked to the source, approvals bound to a content fingerprint, dates only from the
customer, and every manual posting verified against a fresh export.

Finance POD: anyone holding a capacity (finance_pod.access builds that PodAccess). A
Finance Admin holds every capacity, but segregation of duties still applies to them.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends

from src.app.auth.dependencies import AdminUser
from src.app.auth.models import User, UserRole
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.workflows import PodKey, WorkflowSpec, workflows_in

ALL_ENTITIES = None  # a capacity granted for every legal entity


@dataclass(frozen=True)
class PodAccess:
    user: User
    pod: PodKey = PodKey.SERVICE
    # Finance POD: capacity -> the entities it is held for (ALL_ENTITIES: every entity)
    capacities: Mapping[str, frozenset[uuid.UUID] | None] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return self.user.role == UserRole.FINANCE_ADMIN

    def holds(self, capacity: str, entity_id: uuid.UUID | None = None) -> bool:
        if self.is_admin:
            return True
        if capacity not in self.capacities:
            return False
        entities = self.capacities[capacity]
        return entities is ALL_ENTITIES or entity_id is None or entity_id in entities

    def holds_any(self, capacities: frozenset[str] | set[str], entity_id: uuid.UUID) -> bool:
        return any(self.holds(c, entity_id) for c in capacities)


async def get_pod_access(user: AdminUser) -> PodAccess:
    """403 for anyone but a Finance Admin (AdminUser refuses them)."""
    return PodAccess(user=user)


PodAccessDep = Annotated[PodAccess, Depends(get_pod_access)]


def _out(spec: WorkflowSpec) -> WorkflowOut:
    return WorkflowOut(
        key=spec.key,
        pod=spec.pod,
        name=spec.name,
        prefix=spec.prefix,
        description=spec.description,
        required=sorted(spec.required),
        signoff_as=spec.signoff_as,
        signoffs=list(spec.signoffs),
    )


def workflows_for(pod: PodKey = PodKey.SERVICE) -> list[WorkflowOut]:
    return [_out(spec) for spec in workflows_in(pod)]
