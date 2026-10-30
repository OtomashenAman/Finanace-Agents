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


class AppCredentialsError(AppError):
    status_code = 409
    code = "app_credentials_missing"
    message = "Add your QuickBooks app's Client ID and Client Secret first."


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
