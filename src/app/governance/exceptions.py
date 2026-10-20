from src.app.core.errors import AppError


class PolicyNotFoundError(AppError):
    status_code = 404
    code = "policy_not_found"
    message = "This agent has no adjustable thresholds."


class InvalidApprovalMatrixError(AppError):
    status_code = 422
    code = "invalid_approval_matrix"
