from src.app.core.errors import AppError


class SnapshotNotFoundError(AppError):
    status_code = 404
    code = "snapshot_not_found"
    message = "Snapshot not found."


class SnapshotInvalidError(AppError):
    """The source doesn't meet the contract; nothing was imported."""

    status_code = 422
    code = "snapshot_invalid"


class SnapshotTooLargeError(AppError):
    status_code = 413
    code = "snapshot_too_large"


class DemoSnapshotNotAllowedError(AppError):
    status_code = 422
    code = "demo_snapshot_not_allowed"
    message = (
        "This installation doesn't accept demonstration data (SYNTHETIC_DEMO or a QuickBooks "
        "sandbox). Import an authorized read-only export of the company's books."
    )


class SnapshotConflictError(AppError):
    status_code = 409
    code = "snapshot_conflict"
