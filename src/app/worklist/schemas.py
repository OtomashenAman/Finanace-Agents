from datetime import datetime
from typing import Literal

from pydantic import BaseModel

WorkKind = Literal[
    "approve",
    "changes_requested",
    "validation_failed",
    "ready_to_submit",
    "draft",
    "data_source",
    "locked_account",
    "password_reset",
    "waiting",
    "user_data_source",
]


class WorkItem(BaseModel):
    kind: WorkKind
    title: str  # e.g. "RUN-01006 · Bill 195"
    detail: str | None  # why it's here: the reviewer's comment, the error, the counts
    context: str | None  # e.g. "AP Invoice · US01 · Demo User"
    since: datetime  # age is measured from this
    overdue: bool  # past the review SLA, or a stale draft
    high_priority: bool
    action_label: str | None  # None for information-only items
    link: str  # app path to open


class Worklist(BaseModel):
    action: list[WorkItem]  # needs the viewer, most urgent first
    waiting: list[WorkItem]  # the viewer's items waiting on someone else
    info: list[WorkItem]  # good to know, nothing to do (admins: users' connection problems)
    review_sla_hours: int
    stale_draft_days: int
