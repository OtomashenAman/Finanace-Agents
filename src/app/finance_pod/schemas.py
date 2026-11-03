import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

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
    area: Literal["AP", "AR"]
    name: str
    prefix: str
    description: str
    open: int
    approved: int
    completed_30d: int
    measures: list[MeasureOut]


QueueType = Literal["decide", "run", "mail", "post", "verify", "review"]


class QueueItem(BaseModel):
    """Something waiting on the viewer that they may do now: a person's step whose capacity
    they hold, an agent step they may start, a drafted mail they send, an ERP posting they
    post or verify, or an open review task on a case they see."""

    type: QueueType = "decide"
    case_id: uuid.UUID
    reference: str
    workflow: WorkflowKey
    case_title: str
    step_key: str  # the step (or, for mail / postings / reviews, what it is)
    step_title: str  # what to do, in words
    kind: StepKind | None = None
    waiting_since: datetime


AiKind = Literal["agent_step", "posted", "verified"]


class AiEvent(BaseModel):
    at: datetime
    kind: AiKind
    summary: str
    case_id: uuid.UUID | None
    reference: str | None


class FinanceAi(BaseModel):
    """What the agents and the app did lately, as the audit trail records it."""

    last_7_days: dict[str, int]  # kind -> count
    recent: list[AiEvent]


class FinanceKpis(BaseModel):
    open_ap: int
    open_ar: int
    erp_pending: int  # postings to post or verify in ERPNext
    # From the newest snapshot holding sales invoices (None: no AR data, or not the viewer's)
    overdue_receivables: Decimal | None = None
    overdue_clients: int = 0
    currency: str | None = None
    last_snapshot_at: datetime | None = None
    source_name: str | None = None


class FinanceDashboard(BaseModel):
    workflows: list[WorkflowTile]
    my_queue: list[QueueItem]
    kpis: FinanceKpis | None = None
    ai: FinanceAi | None = None
