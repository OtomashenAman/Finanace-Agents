import uuid
from datetime import date, datetime

from pydantic import BaseModel

from src.app.agent_catalog.runs.models import NarrativeStatus


class LlmTotals(BaseModel):
    calls: int
    ok: int
    failed: int
    not_configured: int
    failure_rate: float  # failed / calls, 0..1
    with_guard_warnings: int  # outputs the guard corrected or flagged
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    avg_latency_ms: int | None
    p95_latency_ms: int | None


class LlmDay(BaseModel):
    day: date
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    p95_latency_ms: int | None


class LlmBreakdown(BaseModel):
    key: str  # model id, or agent key
    label: str
    calls: int
    failed: int
    input_tokens: int
    output_tokens: int
    avg_latency_ms: int | None


class LlmCallRun(BaseModel):
    id: uuid.UUID
    reference: str
    agent_key: str
    agent_name: str


class LlmCall(BaseModel):
    id: uuid.UUID
    created_at: datetime
    status: NarrativeStatus
    provider: str
    model: str
    prompt_version: str
    run: LlmCallRun
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    guard_warnings: list[str]
    error: str | None


class LlmSummary(BaseModel):
    days: int
    since: datetime
    totals: LlmTotals
    daily: list[LlmDay]  # every day in the window, oldest first (zeros included)
    by_model: list[LlmBreakdown]
    by_agent: list[LlmBreakdown]
    recent_failures: list[LlmCall]
    recent_calls: list[LlmCall]
