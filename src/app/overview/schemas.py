import uuid
from datetime import datetime

from pydantic import BaseModel


class OverviewKpis(BaseModel):
    active_agents: int
    runs_this_month: int
    pending_review: int
    high_priority: int


class WorklistItem(BaseModel):
    """One open run needing attention."""

    run_id: uuid.UUID
    agent_key: str
    agent_name: str
    reference: str  # business reference (e.g. INV-2048) or RUN-01048
    status: str
    status_label: str
    priority: str
    created_at: datetime


class AdminControls(BaseModel):
    entity: str
    period_label: str  # e.g. "October 2026"
    review_sla_hours: int
    connector_health: str
    model_execution: str


class OverviewSummary(BaseModel):
    period: str  # YYYY-MM
    entity: str
    kpis: OverviewKpis
    worklist: list[WorklistItem]
    controls: AdminControls | None  # Finance Admin only
