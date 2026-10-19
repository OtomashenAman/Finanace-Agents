"""Which action is allowed in which run status (the maker-checker state machine)."""

from enum import StrEnum

from src.app.agent_catalog.runs.exceptions import InvalidRunStateError
from src.app.agent_catalog.runs.models import ReviewDecision, RunStatus


class RunAction(StrEnum):
    EDIT = "edit"  # change input or documents
    ANALYZE = "analyze"
    SUBMIT = "submit"
    REVIEW = "review"
    DELETE = "delete"


EDITABLE = frozenset(
    {
        RunStatus.DRAFT,
        RunStatus.VALIDATION_FAILED,
        RunStatus.ANALYZED,
        RunStatus.CHANGES_REQUESTED,
    }
)

ALLOWED: dict[RunAction, frozenset[RunStatus]] = {
    RunAction.EDIT: EDITABLE,
    RunAction.ANALYZE: EDITABLE,
    RunAction.SUBMIT: frozenset({RunStatus.ANALYZED}),
    RunAction.REVIEW: frozenset({RunStatus.PENDING_APPROVAL}),
    RunAction.DELETE: frozenset({RunStatus.DRAFT, RunStatus.VALIDATION_FAILED}),
}

REVIEW_OUTCOME: dict[ReviewDecision, RunStatus] = {
    ReviewDecision.APPROVED: RunStatus.APPROVED,
    ReviewDecision.REJECTED: RunStatus.REJECTED,
    ReviewDecision.CHANGES_REQUESTED: RunStatus.CHANGES_REQUESTED,
}

STATUS_LABELS: dict[RunStatus, str] = {
    RunStatus.DRAFT: "Draft",
    RunStatus.VALIDATION_FAILED: "Validation failed",
    RunStatus.ANALYZED: "Needs human review",
    RunStatus.PENDING_APPROVAL: "Pending approval",
    RunStatus.CHANGES_REQUESTED: "Changes requested",
    RunStatus.APPROVED: "Approved",
    RunStatus.REJECTED: "Rejected",
}


def is_allowed(status: RunStatus, action: RunAction) -> bool:
    return status in ALLOWED[action]


def ensure_allowed(status: RunStatus, action: RunAction) -> None:
    if not is_allowed(status, action):
        raise InvalidRunStateError(
            f"Can't {action.value} a run that is '{STATUS_LABELS[status].lower()}'."
        )
