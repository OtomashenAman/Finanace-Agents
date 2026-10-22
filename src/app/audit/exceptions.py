from src.app.core.errors import AppError


class InvalidCursorError(AppError):
    status_code = 422
    code = "invalid_cursor"
    message = "This page link is invalid. Reload the audit trail."
