from src.app.core.errors import AppError


class DataSourceNotFoundError(AppError):
    # Also for other users' sources: don't reveal that they exist
    status_code = 404
    code = "data_source_not_found"
    message = "Data source not found."


class RecordNotFoundError(AppError):
    status_code = 404
    code = "record_not_found"
    message = "Record not found in this data source."


class IntegrationNotConfiguredError(AppError):
    status_code = 409
    code = "integration_not_configured"
    message = "QuickBooks isn't set up yet. Ask your Finance Admin to add the QuickBooks app."


class SourceNotSyncableError(AppError):
    status_code = 409
    code = "source_not_syncable"

    def __init__(self, message: str = "Authorize this QuickBooks connection first.") -> None:
        super().__init__(message)


class SyncFailedError(AppError):
    status_code = 502
    code = "sync_failed"


class UploadRejectedError(AppError):
    status_code = 422
    code = "upload_rejected"


class ClientSecretRequiredError(AppError):
    status_code = 422
    code = "client_secret_required"
    message = "Enter the Client Secret."
