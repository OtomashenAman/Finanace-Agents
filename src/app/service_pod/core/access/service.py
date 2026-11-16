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

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from src.app.auth.dependencies import CurrentUser
from src.app.auth.exceptions import PermissionDeniedError
from src.app.auth.models import Area, User
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey


@dataclass(frozen=True)
class PodAccess:
    user: User
    workflows: frozenset[WorkflowKey]

    @property
    def is_admin(self) -> bool:
        return self.user.is_admin

    def allows(self, workflow: str) -> bool:
        return workflow in self.workflows


# The Service POD access of the request being served (None outside a Service POD request:
# background jobs and system code are not limited)
_current: ContextVar[PodAccess | None] = ContextVar("pod_access", default=None)


def current_access() -> PodAccess | None:
    return _current.get()


async def get_pod_access(user: CurrentUser) -> PodAccess:
    """403 for anyone not given the Service POD (or given no workflow in it)."""
    if not user.can_use(Area.SERVICE_POD):
        raise PermissionDeniedError
    access = PodAccess(user=user, workflows=frozenset(WorkflowKey(w) for w in user.workflows()))
    _current.set(access)
    return access


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
