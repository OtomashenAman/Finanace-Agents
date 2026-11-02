from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.app.service_pod.core.steps.spec import StepKind, StepStatus


class L5Out(BaseModel):
    code: str
    text: str
    status: StepStatus
    result: dict[str, Any] | None
    note: str | None  # e.g. why it doesn't apply, or why it failed
    done_by: str | None  # a person's name, "Agent" or "System"
    done_at: datetime | None
    result_schema: dict[str, Any]  # JSON schema of the result a person fills in


class StepOut(BaseModel):
    key: str
    l4: str
    title: str
    kind: StepKind
    capacity: str | None
    after: list[str]
    status: StepStatus
    blocked: str | None  # why the viewer can't act on it now (None: they can)
    l5: list[L5Out]
