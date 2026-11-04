"""Treasury Forecast: the case selection, the actions' payloads and the screens' responses."""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from src.app.service_pod.core.snapshots.schemas import SnapshotSummary

Scenario = Literal["optimistic", "stress"]


class TreasurySelection(BaseModel):
    """The whole entity's cash from the snapshot date; nothing to choose but the source."""


class ReviewReceiptPayload(BaseModel):
    """The Treasury Head's review of one imported tranche."""

    receipt_id: str = Field(min_length=1, max_length=100)
    include: bool
    probability: Decimal = Field(default=Decimal(1), ge=0, le=1, decimal_places=4)
    rationale: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reason_below_certainty(self) -> Self:
        if self.include and self.probability < 1 and len((self.rationale or "").strip()) < 10:
            raise ValueError("a probability below 1 needs a rationale (at least 10 characters)")
        return self


class AddShiftPayload(BaseModel):
    """Optimistic / Stress: move part of an existing receipt or outflow to an explicit date."""

    scenario: Scenario
    event_id: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    to_date: date
    note: str = Field(min_length=20, max_length=1000)


class RemoveShiftPayload(BaseModel):
    scenario: Scenario
    shift_id: str = Field(min_length=1, max_length=20)


class CashSource(BaseModel):
    snapshot: SnapshotSummary
    opening_cash: Decimal | None
    policy_buffer: Decimal | None
    checks: list[str]  # what would stop a forecast on this source (empty: none)
    approved_outflows: Decimal
    commitments: int  # approved AR promises with a date, on this entity


class TreasuryCaseRow(BaseModel):
    id: str
    reference: str
    title: str
    status: str
    as_of: str


class TreasurySources(BaseModel):
    sources: list[CashSource]
    cases: list[TreasuryCaseRow]
