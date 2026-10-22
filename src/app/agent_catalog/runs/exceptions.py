from src.app.auth.exceptions import PermissionDeniedError
from src.app.core.errors import AppError


class RunNotFoundError(AppError):
    status_code = 404
    code = "run_not_found"
    message = "Run not found."


class InvalidRunStateError(AppError):
    status_code = 409
    code = "invalid_run_state"
    message = "This action isn't allowed in the run's current status."


class WorkspaceUnavailableError(AppError):
    status_code = 409
    code = "workspace_unavailable"
    message = "This agent's workspace isn't available yet."


class RunPermissionError(PermissionDeniedError):
    """403 with a specific reason (preparer only, segregation of duties...)."""


class DocumentRejectedError(AppError):
    status_code = 422
    code = "document_rejected"
    message = "This file can't be used."


class DocumentTooLargeError(AppError):
    status_code = 413
    code = "document_too_large"
    message = "This file is too large."


class DocumentConflictError(AppError):
    status_code = 409
    code = "document_conflict"
    message = "This file can't be added."


class DocumentNotFoundError(AppError):
    status_code = 404
    code = "document_not_found"
    message = "Document not found."
