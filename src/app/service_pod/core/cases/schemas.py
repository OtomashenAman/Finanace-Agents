import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from src.app.entities.schemas import EntityRef
from src.app.service_pod.core.cases.models import (
    ActionStatus,
    CaseStatus,
    CommitmentStatus,
    Decision,
    Gate,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from src.app.service_pod.core.messaging.schemas import ArtifactOut, MessageOut
from src.app.service_pod.core.snapshots.schemas import SnapshotSummary
from src.app.service_pod.core.tasks.schemas import TaskOut
from src.app.service_pod.core.workflows import WorkflowKey

JsonObject = dict[str, Any]


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class CaseCreate(BaseModel):
    workflow: WorkflowKey
    snapshot_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    selection: JsonObject = {}


class CaseSummary(BaseModel):
    id: uuid.UUID
    reference: str
    workflow: WorkflowKey
    title: str
    status: CaseStatus
    stage: str
    version: int
    entity: EntityRef
    owner: PersonRef
    snapshot_id: uuid.UUID
    is_demo: bool
    open_review_tasks: int
    created_at: datetime
    updated_at: datetime


class ApprovalOut(BaseModel):
    id: uuid.UUID
    gate: Gate
    decision: Decision
    user: PersonRef
    comment: str | None
    content_hash: str
    policy_version: str | None
    valid: bool  # still matches the case's current content
    created_at: datetime


class ReviewTaskOut(BaseModel):
    id: uuid.UUID
    kind: ReviewTaskKind
    subject: str | None
    detail: str
    blocking: bool
    requirement: JsonObject | None  # what settles it when a person's note isn't enough
    status: ReviewTaskStatus
    resolution: str | None
    created_by: str | None  # None: raised by the system
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class OwnedActionOut(BaseModel):
    id: uuid.UUID
    title: str
    owner: PersonRef
    due_date: date
    status: ActionStatus
    outcome: str | None
    created_at: datetime
    updated_at: datetime


class CommitmentOut(BaseModel):
    id: uuid.UUID
    invoice_id: str
    invoice_number: str
    amount: Decimal
    expected_date: date | None
    probability: Decimal
    probability_rationale: str | None
    quote: str | None
    source_message_id: uuid.UUID | None
    status: CommitmentStatus
    created_by: str | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime


class CaseDetail(CaseSummary):
    snapshot: SnapshotSummary
    selection: JsonObject
    state: JsonObject
    completed_at: datetime | None
    fingerprint: str
    my_roles: list[str]
    approvals: list[ApprovalOut]
    review_tasks: list[ReviewTaskOut]
    owned_actions: list[OwnedActionOut]
    commitments: list[CommitmentOut]
    messages: list[MessageOut]
    artifacts: list[ArtifactOut]
    posting_tasks: list[TaskOut]
    blockers: list[str]  # what stops submission / approval now
    completion_blockers: list[str]
    # action -> None when the viewer may do it now, else the reason they can't
    allowed_actions: dict[str, str | None]


class ReviewQueueItem(BaseModel):
    """An open review task, for the AI Review queue."""

    task: ReviewTaskOut
    case_id: uuid.UUID
    case_reference: str
    workflow: WorkflowKey
    case_title: str


# --- action payloads -------------------------------------------------------------------


class CaseAction(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    expected_version: int = Field(ge=1)
    payload: JsonObject = {}


class EditPayload(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    selection: JsonObject | None = None
    state: JsonObject | None = None


class EmptyPayload(BaseModel):
    pass


class DecisionPayload(BaseModel):
    decision: Decision
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _comment_unless_approved(self) -> "DecisionPayload":
        if self.decision != Decision.APPROVED and not (self.comment and self.comment.strip()):
            raise ValueError("Say why: a comment is required unless you approve.")
        return self


class CancelPayload(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class AddReviewTaskPayload(BaseModel):
    kind: ReviewTaskKind
    subject: str | None = Field(default=None, max_length=200)
    detail: str = Field(min_length=3, max_length=4000)
    blocking: bool = True


class ResolveReviewTaskPayload(BaseModel):
    task_id: uuid.UUID
    resolution: str = Field(min_length=5, max_length=4000)


class AddActionPayload(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    owner_id: uuid.UUID
    due_date: date


class UpdateActionPayload(BaseModel):
    action_id: uuid.UUID
    status: ActionStatus
    outcome: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _outcome_when_closed(self) -> "UpdateActionPayload":
        if self.status != ActionStatus.OPEN and not (self.outcome and self.outcome.strip()):
            raise ValueError("Record the outcome when closing an action.")
        return self


class ProposeCommitmentPayload(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    expected_date: date | None = None
    probability: Decimal = Field(default=Decimal(1), ge=0, le=1, decimal_places=4)
    probability_rationale: str | None = Field(default=None, max_length=2000)
    quote: str | None = Field(default=None, max_length=4000)
    source_message_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _rationale_below_certainty(self) -> "ProposeCommitmentPayload":
        if self.probability < 1 and not (
            self.probability_rationale and self.probability_rationale.strip()
        ):
            raise ValueError("Explain why the probability is below 1.")
        return self


class RefreshSourcePayload(BaseModel):
    snapshot_id: uuid.UUID


class DecideCommitmentPayload(BaseModel):
    commitment_id: uuid.UUID
    decision: Literal["approved", "rejected"]
