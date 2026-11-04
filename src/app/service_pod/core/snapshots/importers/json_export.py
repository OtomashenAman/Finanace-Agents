"""A normalized read-only export (JSON)."""

import json
from decimal import Decimal

from pydantic import ValidationError

from src.app.core.config import get_settings
from src.app.service_pod.core.snapshots.contract import (
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import (
    SnapshotInvalidError,
    SnapshotTooLargeError,
)
from src.app.service_pod.core.snapshots.importers.base import check_row_limits, validation_message


def parse_json_export(data: bytes) -> SnapshotDocument:
    limit = get_settings().pod_snapshot_max_bytes
    if len(data) > limit:
        raise SnapshotTooLargeError(f"Exports can be at most {limit // (1024 * 1024)} MB.")
    try:
        raw = json.loads(data, parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotInvalidError(f"Not valid JSON: {exc}") from exc
    try:
        doc = SnapshotDocument.model_validate(raw)
    except ValidationError as exc:
        raise SnapshotInvalidError(validation_message(exc)) from exc
    check_row_limits(doc)
    return doc
