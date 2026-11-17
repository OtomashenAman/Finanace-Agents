"""Who may use the Service POD, and which parts of it.

A Finance Admin has every workflow and gives every sign-off. Everyone else (AR Specialist,
Accountant, Treasury Analyst, FP&A Analyst, Controller, User) works only in the workflows
an admin gave them (User.pod_workflows) and prepares: they open and work cases, draft
emails, upload documents and import sources. Signing off is the Finance Admin's: approving,
completing or cancelling a case, deciding commitments and documents, sending email,
recording postings and removing sources.

What keeps the work right beyond that are the checks that need no second person: figures
locked to the source, approvals bound to a content fingerprint, dates only from the
customer, and every manual posting verified against a fresh export.

The access of the current request is also kept in a context variable, so load_case() can
refuse cases outside the person's workflows wherever a case is reached (messages, tasks,
artifacts, workflow endpoints) without passing it through every call.
"""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import ColumnElement, select

from src.app.auth.dependencies import CurrentUser
from src.app.auth.exceptions import PermissionDeniedError
from src.app.auth.models import Area, User
from src.app.core.db import SessionDep
from src.app.entities.service import assigned_entity_ids
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey


@dataclass(frozen=True)
class PodAccess:
    user: User
    workflows: frozenset[WorkflowKey]
    # The legal entities whose books and cases they see; None: every one (Finance Admins)
    entity_ids: frozenset[uuid.UUID] | None = None

    @property
    def is_admin(self) -> bool:
        return self.user.is_admin

    def allows(self, workflow: str) -> bool:
        return workflow in self.workflows

    def allows_entity(self, entity_id: uuid.UUID) -> bool:
        return self.entity_ids is None or entity_id in self.entity_ids


# The Service POD access of the request being served (None outside a Service POD request:
# background jobs and system code are not limited)
_current: ContextVar[PodAccess | None] = ContextVar("pod_access", default=None)


def current_access() -> PodAccess | None:
    return _current.get()


async def get_pod_access(user: CurrentUser, session: SessionDep) -> PodAccess:
    """403 for anyone not given the Service POD (or given no workflow in it)."""
    if not user.can_use(Area.SERVICE_POD):
        raise PermissionDeniedError
    entity_ids = (
        None if user.is_admin else frozenset(await session.scalars(assigned_entity_ids(user.id)))
    )
    access = PodAccess(
        user=user,
        workflows=frozenset(WorkflowKey(w) for w in user.workflows()),
        entity_ids=entity_ids,
    )
    _current.set(access)
    return access


def snapshot_scope() -> list[ColumnElement[bool]]:
    """Filters keeping only the snapshots the current person may see (their legal entities).
    Empty outside a Service POD request or for a Finance Admin."""
    access = current_access()
    if access is None or access.entity_ids is None:
        return []
    return [PodSnapshot.entity_id.in_(access.entity_ids)]


def case_scope() -> list[ColumnElement[bool]]:
    """Filters keeping only the cases the current person may see: their workflows, and their
    legal entities. Empty outside a Service POD request."""
    access = current_access()
    if access is None:
        return []
    scope: list[ColumnElement[bool]] = [PodCase.workflow.in_(access.workflows)]
    if access.entity_ids is not None:
        scope.append(PodCase.entity_id.in_(access.entity_ids))
    return scope


def visible_case_ids() -> Any:
    """The ids of the cases the current person may see, as a subquery."""
    return select(PodCase.id).where(*case_scope())


PodAccessDep = Annotated[PodAccess, Depends(get_pod_access)]


async def get_pod_admin(access: PodAccessDep) -> PodAccess:
    """Sign-off and housekeeping: Finance Admins only."""
    if not access.is_admin:
        raise PermissionDeniedError
    return access


PodAdminDep = Annotated[PodAccess, Depends(get_pod_admin)]


def require_admin(access: PodAccess) -> None:
    if not access.is_admin:
        raise PermissionDeniedError


def require_workflow(access: PodAccess, workflow: WorkflowKey) -> None:
    if not access.allows(workflow):
        raise PermissionDeniedError


def for_workflow(workflow: WorkflowKey) -> Any:
    """Dependency for a workflow's own endpoints: 403 unless the person has that workflow."""

    async def checker(access: PodAccessDep) -> PodAccess:
        require_workflow(access, workflow)
        return access

    return Depends(checker)


def workflows_for(access: PodAccess) -> list[WorkflowOut]:
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
        if access.allows(spec.key)
    ]
