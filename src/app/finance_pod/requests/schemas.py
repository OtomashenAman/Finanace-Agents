import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.app.finance_pod.approvals.schemas import BudgetCheck, DecisionOut, RouteStep
from src.app.finance_pod.requests.models import CodingSource, RequestFileKind, RequestStatus

Code = Field(default=None, max_length=40)


class LineIn(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    category: str | None = Field(default=None, max_length=64)
    catalogue_item_code: str | None = Code

    @field_validator("category")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return v.strip().lower() or None if v else None


class RequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(default="", max_length=4000)
    needed_by: date | None = None
    cost_centre_code: str | None = Code
    lab_code: str | None = Code
    project_code: str | None = Code
    grant_code: str | None = Code
    lines: list[LineIn] = Field(default_factory=list, max_length=100)
    source_text: str | None = Field(default=None, max_length=8000)


class RequestUpdate(RequestIn):
    expected_version: int


class VersionIn(BaseModel):
    expected_version: int


class CancelIn(VersionIn):
    reason: str = Field(min_length=1, max_length=500)


class TextIn(BaseModel):
    text: str = Field(min_length=5, max_length=8000)


class LineOut(BaseModel):
    description: str
    quantity: Decimal
    unit: str | None
    unit_price: Decimal | None
    category: str | None
    catalogue_item_code: str | None
    amount: Decimal


class FileOut(BaseModel):
    id: uuid.UUID
    kind: RequestFileKind
    filename: str
    content_type: str
    size: int
    created_at: datetime


class Problem(BaseModel):
    """Something the request agent flagged (1.1.2.c). Blocking ones stop the submit."""

    field: str
    message: str
    blocking: bool


class PriceCheck(BaseModel):
    """A request line against the catalogue / contract prices (1.1.2.b)."""

    line: int  # 1-based
    status: Literal["matches", "above_contract", "below_contract", "no_estimate", "no_match"]
    item_code: str | None = None
    item_description: str | None = None
    contract_price: Decimal | None = None
    vendor_code: str | None = None
    vendor_name: str | None = None
    contract_ref: str | None = None
    difference: Decimal | None = None  # (estimate - contract price) x quantity
    how: Literal["item_code", "description"] | None = None


class CodingSuggestion(BaseModel):
    """The request agent's coding suggestion (1.1.2.a), checked against the reference data."""

    cost_centre_code: str | None
    lab_code: str | None
    project_code: str | None
    grant_code: str | None
    line_categories: list[str | None]
    reason: str
    source: Literal["ai", "history"]
    provenance: dict[str, Any] | None = None


class Enrichment(BaseModel):
    ran_at: datetime
    suggestion: CodingSuggestion | None
    suggestion_note: str | None  # why there is none (no AI, nothing fitting...)
    price_checks: list[PriceCheck]
    problems: list[Problem]
    quotes_needed: int  # quotes sourcing will need (0 below the threshold)


class RequestSummary(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    status: RequestStatus
    requester_id: uuid.UUID
    requester_name: str
    total: Decimal
    currency: str
    cost_centre_code: str | None
    needed_by: date | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    blocking_problems: int | None  # None = the agent hasn't checked it yet


class RequestOut(RequestSummary):
    version: int
    purpose: str
    lab_code: str | None
    project_code: str | None
    grant_code: str | None
    coding_source: CodingSource | None
    source_text: str | None
    lines: list[LineOut]
    files: list[FileOut]
    enrichment: Enrichment | None
    closed_at: datetime | None
    can_edit: bool
    # Phase 1.2: the budget agent's check and the approval route of the current round
    round: int
    budget_check: BudgetCheck | None
    route: list[RouteStep]
    current_step: RouteStep | None
    can_decide: bool
    decide_blocker: str | None
    decisions: list[DecisionOut]  # every round, oldest first


class DraftLine(BaseModel):
    description: str
    quantity: Decimal
    unit: str | None
    unit_price: Decimal | None


class RequestDraft(BaseModel):
    """Free text turned into the request form (1.1.1.a in chat). Nothing is saved."""

    title: str
    purpose: str
    needed_by: date | None
    lines: list[DraftLine]
    notes: list[str]  # what the agent couldn't tell from the text
    provenance: dict[str, Any]
