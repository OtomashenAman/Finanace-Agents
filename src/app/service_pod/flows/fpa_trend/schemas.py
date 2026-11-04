"""FP&A Trend Intelligence: the case selection, the actions' payloads and the AI's output."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from src.app.service_pod.core.snapshots.contract import Period
from src.app.service_pod.core.snapshots.schemas import SnapshotSummary


class FpaSelection(BaseModel):
    start: Period
    end: Period
    business_unit: str | None = Field(default=None, max_length=200)  # None: the whole company

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("the start month must come before the end month")
        return self


class CorrectionLine(BaseModel):
    account_id: str = Field(min_length=1, max_length=100)
    debit: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=2)
    credit: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=2)
    memo: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_side(self) -> Self:
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("each line is either a debit or a credit")
        return self


class ProposeCorrectionPayload(BaseModel):
    """A manual journal to correct the books (TDD: current-period GL evidence, a substantive
    rationale, mapped P&L accounts and balanced lines). The Finance Admin posts it."""

    period: Period
    evidence_gl_line_id: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=20, max_length=2000)
    lines: list[CorrectionLine] = Field(min_length=2, max_length=20)


class CorrectionRef(BaseModel):
    correction_id: str = Field(min_length=1, max_length=20)


class Statement(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    fact_ids: list[str] = Field(default_factory=list, max_length=20)


class SetCommentaryPayload(BaseModel):
    """Commentary written (or edited) by a person: it cites facts like the AI's, but a
    person may state figures."""

    highlights: list[Statement] = Field(min_length=1, max_length=12)


class ConfirmMappingPayload(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


# --- what the AI returns (plain fields: provider strict JSON schema) --------------------


class AiStatement(BaseModel):
    text: str = Field(description="One sentence; no digits, currency or percent signs")
    fact_ids: list[str] = Field(description="IDs of the facts this sentence relies on")


class AiFollowUp(BaseModel):
    kind: Literal["question", "validate", "investigate"] = Field(
        description="question: something the figures can't answer; validate: a business "
        "explanation to confirm; investigate: a movement to look into"
    )
    text: str = Field(description="One sentence; no digits, currency or percent signs")
    fact_ids: list[str] = Field(description="IDs of the facts it concerns")


class FpaCommentary(BaseModel):
    highlights: list[AiStatement] = Field(
        description="Two to four findings about the latest month against the month before"
    )
    follow_ups: list[AiFollowUp] = Field(
        description="At most three open questions or checks for the Finance Head"
    )


# --- the workflow's home screen ---------------------------------------------------------


class PeriodSource(BaseModel):
    snapshot: SnapshotSummary
    months: list[str]  # months with P&L lines, oldest first
    business_units: list[str]
    suggested_start: str | None  # the latest six (or fewer) consecutive months
    suggested_end: str | None


class FpaCaseRow(BaseModel):
    id: str
    reference: str
    title: str
    status: str
    start: str
    end: str


class FpaPeriods(BaseModel):
    sources: list[PeriodSource]
    cases: list[FpaCaseRow]
