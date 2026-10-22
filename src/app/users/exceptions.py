from src.app.core.errors import AppError


class UserNotFoundError(AppError):
    status_code = 404
    code = "user_not_found"
    message = "User not found."


class EmailTakenError(AppError):
    status_code = 409
    code = "email_taken"
    message = "A user with this email already exists."


class UnknownAgentError(AppError):
    status_code = 422
    code = "unknown_agent"

    def __init__(self, keys: list[str]) -> None:
        super().__init__(f"Unknown agent(s): {', '.join(sorted(keys))}.")


class SelfManagementError(AppError):
    # An admin locking themselves out would leave nobody able to undo it
    status_code = 409
    code = "self_management"
    message = "You can't remove, deactivate or demote your own account."


class UserHasHistoryError(AppError):
    # Runs and reviews keep their preparer/reviewer for the audit trail
    status_code = 409
    code = "user_has_history"
    message = "This user has runs or reviews on record. Deactivate the account instead."
