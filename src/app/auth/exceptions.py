import math
from datetime import datetime

from src.app.common.clock import utcnow
from src.app.core.errors import AppError


class InvalidCredentialsError(AppError):
    # Same message for unknown email and wrong password: no account enumeration
    status_code = 401
    code = "invalid_credentials"
    message = "Invalid email or password."


class AccountLockedError(AppError):
    status_code = 423
    code = "account_locked"

    def __init__(self, locked_until: datetime) -> None:
        minutes = max(1, math.ceil((locked_until - utcnow()).total_seconds() / 60))
        super().__init__(f"Too many failed attempts. Try again in {minutes} minute(s).")
        self.locked_until = locked_until


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Please sign in."


class TokenExpiredError(NotAuthenticatedError):
    code = "token_expired"
    message = "Session expired."


class InvalidRefreshTokenError(NotAuthenticatedError):
    code = "invalid_refresh_token"
    message = "Your session has ended. Please sign in again."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "permission_denied"
    message = "You don't have access to this resource."
