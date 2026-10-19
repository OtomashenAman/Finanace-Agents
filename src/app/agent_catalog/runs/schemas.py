import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.agent_catalog.agents.fields import FormField
from src.app.agent_catalog.runs.models import (
    FlagSeverity,
    NarrativeStatus,
    ReviewDecision,
    RunPriority,
    RunStatus,
)


class NarrativeOutput(BaseModel):
    """Structured output the LLM must return (validated by the provider)."""

    summary: str = Field(description="2-4 sentence explanation for the reviewer")
    key_points: list[str] = Field(description="At most 5 short points")
    cited_fields: list[str] = Field(description="Keys from input/calculations relied on")
    cited_documents: list[str] = Field(description="Document ids (e.g. D1) relied on")
    missing_evidence: list[str] = Field(description="Evidence a reviewer needs but lacks")
    ambiguities: list[str] = Field(description="Conflicts or unclear points")


class FormSpec(BaseModel):
    agent_key: str
    fields: list[FormField]
    controls: list[str]


class RunInputUpdate(BaseModel):
    """The whole form; missing fields are cleared. Validated against the agent's draft schema."""

    values: dict[str, Any]


class ReviewCreate(BaseModel):
    decision: ReviewDecision
    comment: str = Field(min_length=3, max_length=2000)


class Person(BaseModel):
    id: uuid.UUID
    full_name: str


class FieldError(BaseModel):
    field: str | None
    message: str


class CalculationOut(BaseModel):
    key: str
    label: str
    value: str | None
    kind: str


class FlagOut(BaseModel):
    code: str
    severity: FlagSeverity
    message: str
    field: str | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    extractor: str
    page_count: int | None
    char_count: int
    truncated: bool
    warnings: list[str]
    text_preview: str
    created_at: datetime


class DocumentText(BaseModel):
    id: uuid.UUID
    filename: str
    extracted_text: str


class NarrativeOut(BaseModel):
    status: NarrativeStatus
    provider: str
    model: str
    prompt_version: str
    output: NarrativeOutput | None
    guard_warnings: list[str]
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class ReviewOut(BaseModel):
    id: uuid.UUID
    reviewer: Person
    decision: ReviewDecision
    comment: str
    result_hash: str
    created_at: datetime


class RunPermissions(BaseModel):
    can_edit: bool
    can_analyze: bool
    can_submit: bool
    can_review: bool
    can_delete: bool


class RunSummary(BaseModel):
    id: uuid.UUID
    reference: str  # RUN-01048
    agent_key: str
    agent_name: str
    business_reference: str | None  # e.g. the invoice number
    status: RunStatus
    status_label: str
    priority: RunPriority
    headline: str | None
    preparer: Person
    created_at: datetime
    updated_at: datetime


class RunDetail(RunSummary):
    input: dict[str, Any]
    validation_errors: list[FieldError] | None
    proposed_decision: str | None
    policy_version: str | None
    calculations: list[CalculationOut]
    flags: list[FlagOut]
    controls: list[str]
    reviewer_label: str
    documents: list[DocumentOut]
    narrative: NarrativeOut | None
    reviews: list[ReviewOut]
    result_hash: str | None
    analyzed_at: datetime | None
    submitted_at: datetime | None
    decided_at: datetime | None
    permissions: RunPermissions
