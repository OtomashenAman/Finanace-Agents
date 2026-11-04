"""Financial Reporting: the case selection and the screens' responses."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.service_pod.core.snapshots.contract import Period
from src.app.service_pod.core.snapshots.schemas import SnapshotSummary


class ReportingSelection(BaseModel):
    month: Period  # the report month; it is compared with the calendar month before
    business_unit: str | None = Field(default=None, max_length=200)


class ReportMonth(BaseModel):
    month: str
    closed: bool
    balance_sheet: bool
    prior_available: bool  # the month before has P&L lines too


class ReportSource(BaseModel):
    snapshot: SnapshotSummary
    months: list[ReportMonth]  # newest first
    business_units: list[str]
    suggested: str | None  # the latest closed month that can be compared


class ReportCaseRow(BaseModel):
    id: str
    reference: str
    title: str
    status: str
    month: str


class ReportMonths(BaseModel):
    sources: list[ReportSource]
    cases: list[ReportCaseRow]
    internal_recipients: list[str]  # who the CFO may send the pack to


class PackOut(BaseModel):
    id: uuid.UUID
    number: int
    sha256: str
    size: int
    content_hash: str
    source_sha: str
    reviewers: list[dict[str, Any]]
    artifact_id: uuid.UUID
    current: bool  # still binds the case's content (an edit since makes it history)
    created_at: datetime
