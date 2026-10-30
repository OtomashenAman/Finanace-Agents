from src.app.core.errors import AppError


class CaseNotFoundError(AppError):
    status_code = 404
    code = "case_not_found"
    message = "Case not found."


class StaleVersionError(AppError):
    # Someone else changed the case since this screen loaded it
    status_code = 409
    code = "stale_version"
    message = "This case was changed by someone else. Refresh to see the latest version."


class CaseActionError(AppError):
    """The action isn't possible in the case's current state (the message says why)."""

    status_code = 409
    code = "case_action_refused"


class InvalidActionPayloadError(AppError):
    status_code = 422
    code = "invalid_action_payload"


class SourceCoverageError(AppError):
    status_code = 422
    code = "source_coverage"


class CaseSelectionError(AppError):
    """What the case was opened on doesn't fit the workflow (the message says why)."""

    status_code = 422
    code = "case_selection_invalid"
