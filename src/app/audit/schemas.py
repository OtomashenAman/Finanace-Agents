import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from src.app.audit.labels import AuditCategory


class AuditPerson(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class AuditRunLink(BaseModel):
    id: uuid.UUID
    reference: str
    agent_key: str


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    category: AuditCategory | None
    summary: str  # e.g. "Approved RUN-01006"
    outcome: Literal["success", "failure"]
    actor: AuditPerson | None  # None: anonymous (failed sign-in) or a deleted user
    subject_user: AuditPerson | None  # who a user-management event was about
    run: AuditRunLink | None  # the run it concerns, when it still exists and is visible
    # Only for Finance Admins and for the viewer's own actions
    ip: str | None
    user_agent: str | None
    details: dict[str, Any]


class ChainCheckOut(BaseModel):
    checked: int
    valid: bool
    first_broken_seq: int | None
    first_seq: int | None
    last_seq: int | None
    last_hash: str | None
    checked_at: datetime
    retention_days: int


class AuditPage(BaseModel):
    items: list[AuditEventOut]
    next_cursor: str | None  # pass back as ?cursor= for the next (older) page
