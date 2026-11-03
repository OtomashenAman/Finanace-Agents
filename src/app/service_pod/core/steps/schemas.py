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
    # What was filled in before the step was sent back (to start the form from)
    previous: dict[str, Any] | None = None


class NeedsFix(BaseModel):
    """An agent step that won't run until something earlier is fixed."""

    message: str
    fix_step: str | None  # the earlier step to send back and fill in again
    fix_title: str | None


class StepOut(BaseModel):
    key: str
    l4: str
    title: str
    kind: StepKind
    capacity: str | None
    after: list[str]
    status: StepStatus
    blocked: str | None  # why the viewer can't act on it now (None: they can)
    needs: NeedsFix | None = None
    l5: list[L5Out]
