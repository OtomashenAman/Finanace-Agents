import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from src.app.entities.schemas import EntityRef
from src.app.finance_pod.capacities import FinanceCapacity
from src.app.service_pod.core.steps.spec import StepKind
from src.app.service_pod.core.workflows import WorkflowKey


class CapacityOut(BaseModel):
    key: FinanceCapacity
    label: str
    description: str


class HeldCapacity(BaseModel):
    capacity: FinanceCapacity
    label: str
    entities: list[EntityRef] | None  # None: every entity


class FinanceMe(BaseModel):
    is_admin: bool  # holds every capacity (segregation of duties still applies)
    capacities: list[HeldCapacity]
    can_open: list[WorkflowKey]  # workflows this person may open a case of


class AssignmentPerson(BaseModel):
    id: uuid.UUID
    name: str
    email: str


class AssignmentOut(BaseModel):
    id: uuid.UUID
    user: AssignmentPerson
    capacity: FinanceCapacity
    label: str
    entity: EntityRef | None  # None: every entity
    granted_by: str | None
    created_at: datetime


class AssignmentCreate(BaseModel):
    user_id: uuid.UUID
    capacity: FinanceCapacity
    entity_id: uuid.UUID | None = None  # None: every entity


class MeasureOut(BaseModel):
    id: str
    label: str
    unit: str
    value: Decimal | None  # None: not enough cases yet


class WorkflowTile(BaseModel):
    key: WorkflowKey
    name: str
    prefix: str
    description: str
    open: int
    approved: int
    completed_30d: int
    measures: list[MeasureOut]


class QueueItem(BaseModel):
    """A step waiting on the viewer: they hold its capacity and may act on it now."""

    case_id: uuid.UUID
    reference: str
    workflow: WorkflowKey
    case_title: str
    step_key: str
    step_title: str
    kind: StepKind
    waiting_since: datetime


class FinanceDashboard(BaseModel):
    workflows: list[WorkflowTile]
    my_queue: list[QueueItem]
