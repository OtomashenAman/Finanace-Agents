from src.app.core.errors import AppError


class RequestNotFoundError(AppError):
    status_code = 404
    code = "request_not_found"
    message = "Purchase request not found."


class StaleRequestError(AppError):
    status_code = 409
    code = "request_changed"
    message = "Someone changed this request since you opened it. Reload and try again."


class RequestLockedError(AppError):
    status_code = 409
    code = "request_locked"


class NotRequesterError(AppError):
    status_code = 403
    code = "not_requester"
    message = "Only the requester can change this request."


class RequestInvalidError(AppError):
    status_code = 422
    code = "request_invalid"


class RequestFileNotFoundError(AppError):
    status_code = 404
    code = "request_file_not_found"
    message = "File not found."
