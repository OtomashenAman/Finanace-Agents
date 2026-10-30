import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.app.service_pod.core.tasks.models import TaskKind, TaskStatus
from src.app.service_pod.core.workflows import WorkflowKey


class TaskOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_reference: str
    workflow: WorkflowKey
    kind: TaskKind
    reference: str
    status: TaskStatus
    version: int
    instructions: dict[str, Any]
    note: str | None
    proposed_by: str
    approved_by: str | None
    approved_at: datetime | None
    external_txn_id: str | None
    recorded_by: str | None
    recorded_at: datetime | None
    verified_by: str | None
    verified_at: datetime | None
    verification_snapshot_id: uuid.UUID | None
    verification: dict[str, Any] | None
    created_at: datetime
    # action -> None when the viewer may do it now, else the reason they can't
    allowed_actions: dict[str, str | None]


class TaskCreate(BaseModel):
    kind: TaskKind
    reference: str = Field(min_length=1, max_length=100)
    instructions: dict[str, Any]
    note: str | None = Field(default=None, max_length=2000)


class TaskAction(BaseModel):
    action: Literal["approve", "record", "verify", "cancel"]
    expected_version: int = Field(ge=1)
    external_txn_id: str | None = Field(default=None, min_length=1, max_length=100)
    snapshot_id: uuid.UUID | None = None  # the fresh snapshot that proves the posting
    note: str | None = Field(default=None, max_length=2000)
