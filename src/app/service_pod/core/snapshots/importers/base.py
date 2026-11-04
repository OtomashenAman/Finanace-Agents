"""Shared by the importers: readable validation errors and row limits."""

from pydantic import ValidationError

from src.app.core.config import get_settings
from src.app.service_pod.core.snapshots.contract import (
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError

MAX_REPORTED_ERRORS = 5


def validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:MAX_REPORTED_ERRORS]:
        where = ".".join(str(p) for p in err["loc"])
        parts.append(f"{where}: {err['msg']}" if where else err["msg"])
    more = len(exc.errors()) - MAX_REPORTED_ERRORS
    return "; ".join(parts) + (f" (and {more} more)" if more > 0 else "")


def check_row_limits(doc: SnapshotDocument) -> None:
    limit = get_settings().pod_max_rows_per_collection
    for collection in doc.coverage:
        if doc.row_count(collection) > limit:
            raise SnapshotInvalidError(f"{collection.value}: more than {limit} rows.")
