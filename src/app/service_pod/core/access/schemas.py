import uuid

from pydantic import BaseModel, Field

from src.app.auth.models import UserRole
from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import Capacity, WorkflowKey


class WorkflowOut(BaseModel):
    key: WorkflowKey
    name: str
    prefix: str
    description: str
    labels: dict[str, str]  # capacity -> deck role name
    required: list[Collection]
    final_gate: bool
    my_capacities: list[Capacity]


class PodAssignmentIn(BaseModel):
    workflow: WorkflowKey
    capacity: Capacity


class PodAssignmentOut(PodAssignmentIn):
    pass


class PodAssignmentsUpdate(BaseModel):
    assignments: list[PodAssignmentIn] = Field(max_length=40)


class PodUserAccess(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    assignments: list[PodAssignmentOut]
