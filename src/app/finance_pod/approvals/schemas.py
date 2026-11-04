import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from src.app.finance_pod.approvals.models import Decision


class BudgetImpact(BaseModel):
    """One budget line the request draws on, before and after it (1.2.1.a)."""

    budget_id: uuid.UUID | None  # None: no budget line found
    holder: str  # "cost centre CC-100" / "grant GR-22"
    fiscal_year: int
    category: str | None  # the budget line's category (None = whole holder)
    lines: list[int]  # request lines (1-based) charged here
    budget: Decimal
    committed: Decimal  # from the ERP / workbook
    spent: Decimal
    approved_requests: Decimal  # approved in the Finance POD, not yet POs
    available: Decimal  # before this request
    this_request: Decimal
    remaining_after: Decimal
    over_budget: bool


class Finding(BaseModel):
    kind: Literal[
        "over_budget", "no_budget", "unallowable", "grant_period", "uncategorised", "routing"
    ]
    message: str
    # blocking: approval is refused; acknowledge: an approver may approve with a note
    severity: Literal["blocking", "acknowledge", "info"]


class RouteStep(BaseModel):
    """One approval the authority matrix asks for (1.2.1.c)."""

    step: int
    capacity: str
    approver_email: str | None
    approver_name: str | None  # None: no Finance Admin account with that email
    min_amount: Decimal
    status: Literal["waiting", "approved", "rejected", "queried", "pending"]


class BudgetCheck(BaseModel):
    ran_at: datetime
    round: int
    total: Decimal
    currency: str
    fiscal_year: int
    impacts: list[BudgetImpact]
    findings: list[Finding]
    route: list[RouteStep]


class DecisionIn(BaseModel):
    expected_version: int
    decision: Decision
    note: str = Field(default="", max_length=2000)
    acknowledge_budget: bool = False


class DecisionOut(BaseModel):
    id: uuid.UUID
    round: int
    step: int
    capacity: str
    approver_email: str | None
    decided_by_name: str
    decision: Decision
    note: str
    acting_for: str | None
    budget_acknowledged: bool
    self_approval: bool
    created_at: datetime
