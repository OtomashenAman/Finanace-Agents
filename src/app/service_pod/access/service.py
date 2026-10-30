"""Who may do what in the Service POD.

A Finance Admin (the system role) manages assignments and can read everything for
oversight, but takes a financial decision only through a capacity assigned like anyone
else's. Entity scope comes from the legal entity assignments shared with the agents.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.dependencies import CurrentUser
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext
from src.app.core.db import SessionDep
from src.app.entities.service import assigned_entity_ids
from src.app.service_pod.access.exceptions import InvalidAssignmentError, PodForbiddenError
from src.app.service_pod.access.models import PodAssignment
from src.app.service_pod.access.schemas import (
    PodAssignmentIn,
    PodAssignmentOut,
    PodUserAccess,
    WorkflowOut,
)
from src.app.service_pod.snapshots.contract import Collection
from src.app.service_pod.workflows import WORKFLOWS, Capacity, WorkflowKey

CASE_CAPACITIES = frozenset({Capacity.PREPARER, Capacity.REVIEWER, Capacity.FINAL_APPROVER})


@dataclass(frozen=True)
class PodAccess:
    user: User
    capacities: dict[WorkflowKey, frozenset[Capacity]]
    entity_ids: frozenset[uuid.UUID] | None  # None: every entity (Finance Admin)

    @property
    def is_admin(self) -> bool:
        return self.user.role == UserRole.FINANCE_ADMIN

    def has(self, workflow: WorkflowKey, capacity: Capacity) -> bool:
        return capacity in self.capacities.get(workflow, frozenset())

    def require(self, workflow: WorkflowKey, capacity: Capacity, to: str) -> None:
        if not self.has(workflow, capacity):
            spec = WORKFLOWS[workflow]
            role = spec.labels.get(capacity, capacity.value)
            raise PodForbiddenError(f"Only the {role} of {spec.name} can {to}.")

    @property
    def is_poster(self) -> bool:
        return any(Capacity.POSTER in caps for caps in self.capacities.values())

    def require_poster(self, to: str) -> None:
        if not self.is_poster:
            raise PodForbiddenError(f"Only a Finance Admin with posting rights can {to}.")

    def can_see_entity(self, entity_id: uuid.UUID) -> bool:
        return self.entity_ids is None or entity_id in self.entity_ids

    def require_entity(self, entity_id: uuid.UUID) -> None:
        if not self.can_see_entity(entity_id):
            raise PodForbiddenError("You don't work for this legal entity.")

    @property
    def case_workflows(self) -> frozenset[WorkflowKey]:
        """Workflows whose cases the user works on (posting rights alone don't open cases)."""
        if self.is_admin:
            return frozenset(WORKFLOWS)
        return frozenset(w for w, caps in self.capacities.items() if caps & CASE_CAPACITIES)

    @property
    def visible_collections(self) -> frozenset[Collection]:
        if self.is_admin or self.is_poster:
            return frozenset(Collection)
        return frozenset(c for w in self.case_workflows for c in WORKFLOWS[w].visible)


async def load_access(session: AsyncSession, user: User) -> PodAccess:
    rows = await session.execute(
        select(PodAssignment.workflow, PodAssignment.capacity).where(
            PodAssignment.user_id == user.id
        )
    )
    caps: dict[WorkflowKey, set[Capacity]] = {}
    for workflow, capacity in rows:
        caps.setdefault(workflow, set()).add(capacity)
    entity_ids = None
    if user.role != UserRole.FINANCE_ADMIN:
        entity_ids = frozenset(await session.scalars(assigned_entity_ids(user.id)))
    return PodAccess(
        user=user,
        capacities={w: frozenset(c) for w, c in caps.items()},
        entity_ids=entity_ids,
    )


async def get_pod_access(session: SessionDep, user: CurrentUser) -> PodAccess:
    return await load_access(session, user)


PodAccessDep = Annotated[PodAccess, Depends(get_pod_access)]


def workflows_for(access: PodAccess) -> list[WorkflowOut]:
    return [
        WorkflowOut(
            key=spec.key,
            name=spec.name,
            prefix=spec.prefix,
            description=spec.description,
            labels={c.value: label for c, label in spec.labels.items()},
            required=sorted(spec.required),
            final_gate=spec.final_gate,
            my_capacities=sorted(access.capacities.get(spec.key, frozenset())),
        )
        for spec in WORKFLOWS.values()
    ]


# --- admin: assignments -----------------------------------------------------------------


async def list_user_access(session: AsyncSession) -> list[PodUserAccess]:
    users = list(await session.scalars(select(User).where(User.is_active).order_by(User.full_name)))
    rows = await session.execute(
        select(PodAssignment.user_id, PodAssignment.workflow, PodAssignment.capacity)
    )
    by_user: dict[uuid.UUID, list[PodAssignmentOut]] = {}
    for user_id, workflow, capacity in rows:
        by_user.setdefault(user_id, []).append(
            PodAssignmentOut(workflow=workflow, capacity=capacity)
        )
    return [
        PodUserAccess(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            assignments=sorted(
                by_user.get(u.id, []), key=lambda a: (a.workflow.value, a.capacity.value)
            ),
        )
        for u in users
    ]


async def set_user_access(
    session: AsyncSession,
    user_id: uuid.UUID,
    wanted: list[PodAssignmentIn],
    actor: User,
    ctx: RequestContext,
) -> PodUserAccess:
    user = await session.get(User, user_id, with_for_update=True)
    if user is None or not user.is_active:
        raise InvalidAssignmentError("Unknown or inactive user.")
    pairs = {(a.workflow, a.capacity) for a in wanted}
    for workflow, capacity in pairs:
        spec = WORKFLOWS[workflow]
        if capacity not in spec.capacities:
            raise InvalidAssignmentError(f"{spec.name} has no {capacity.value} role.")
    await session.execute(delete(PodAssignment).where(PodAssignment.user_id == user.id))
    session.add_all(PodAssignment(user_id=user.id, workflow=w, capacity=c) for w, c in pairs)
    labels = sorted(f"{w.value}:{c.value}" for w, c in pairs)
    record_event(
        session,
        "pod.assignments_updated",
        ctx,
        actor_id=actor.id,
        user_id=str(user.id),
        assignments=labels,
        summary=f"Changed Service POD access of {user.full_name}: {', '.join(labels) or 'none'}",
    )
    await session.commit()
    return next(u for u in await list_user_access(session) if u.user_id == user.id)
