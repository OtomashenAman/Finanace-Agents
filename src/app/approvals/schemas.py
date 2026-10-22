from datetime import datetime

from src.app.agent_catalog.runs.schemas import RunSummary


class ApprovalItem(RunSummary):
    """A run in the approvals queue (pending) or history (decided)."""

    submitted_at: datetime | None
    decided_at: datetime | None
