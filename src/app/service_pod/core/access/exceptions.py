from src.app.core.errors import AppError


class PodForbiddenError(AppError):
    """403 with the reason (missing capacity, segregation of duties, other entity...)."""

    status_code = 403
    code = "pod_forbidden"
    message = "You don't have access to this."


class InvalidAssignmentError(AppError):
    status_code = 422
    code = "invalid_pod_assignment"
