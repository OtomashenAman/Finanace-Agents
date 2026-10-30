"""Turn source files and connected companies into SnapshotDocuments, one module per source.
Nothing here writes to a source, and nothing missing is invented: absent data stays absent
and shows in the snapshot's coverage."""

from src.app.service_pod.core.snapshots.importers.bank_csv import parse_bank_csv, with_bank_receipts
from src.app.service_pod.core.snapshots.importers.base import check_row_limits
from src.app.service_pod.core.snapshots.importers.json_export import parse_json_export
from src.app.service_pod.core.snapshots.importers.qbxml import parse_qbxml
from src.app.service_pod.core.snapshots.importers.quickbooks_online import from_quickbooks

__all__ = [
    "check_row_limits",
    "from_quickbooks",
    "parse_bank_csv",
    "parse_json_export",
    "parse_qbxml",
    "with_bank_receipts",
]
