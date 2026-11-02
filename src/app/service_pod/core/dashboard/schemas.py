import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from src.app.service_pod.core.workflows import WorkflowKey

# Where a case stands, in the same words as the case page's status chip
# "analysis": an internal workflow (FP&A, Reporting) whose findings are still being written
Phase = Literal["compose", "waiting", "analysis", "review", "ready", "approved", "closed"]
OPEN_PHASES: tuple[Phase, ...] = ("compose", "waiting", "analysis", "review", "ready", "approved")


class MoneyTotal(BaseModel):
    currency: str
    amount: Decimal


class PromiseItem(BaseModel):
    case_id: uuid.UUID
    case_reference: str
    case_title: str
    invoice_number: str
    amount: Decimal
    currency: str
    expected_date: date


class AgingBucket(BaseModel):
    label: str  # e.g. "0-7 days"
    count: int


class OpenCase(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    workflow: WorkflowKey
    phase: Phase
    days_open: int


class EmailHealth(BaseModel):
    provider: str
    simulated: bool
    ready: bool
    problem: str | None
    reads_mailbox: bool  # replies are picked up from the inbox by the worker
    poll_seconds: int | None
    last_reply_at: datetime | None
    sent_30d: int
    replies_30d: int
    avg_reply_hours: float | None  # sent -> reply, over the replies of the last 30 days


class Dashboard(BaseModel):
    """The Service POD at a glance; every figure is counted from the cases, never estimated."""

    open_cases: int
    closed_30d: int
    phases: dict[Phase, int]
    promised: list[MoneyTotal]  # approved payment commitments on cases not cancelled
    due_this_week: list[PromiseItem]  # approved promises dated today .. today + 7
    overdue_promises: list[PromiseItem]  # approved promises whose date has passed
    aging: list[AgingBucket]
    open: list[OpenCase]  # every open case, oldest first
    email: EmailHealth
