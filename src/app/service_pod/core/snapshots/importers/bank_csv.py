"""A bank statement (CSV) added to an earlier snapshot, as a new snapshot."""

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import TypeAdapter, ValidationError

from src.app.core.config import get_settings
from src.app.service_pod.core.snapshots.contract import (
    BankReceipt,
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import (
    SnapshotInvalidError,
    SnapshotTooLargeError,
)
from src.app.service_pod.core.snapshots.importers.base import (
    validation_message,
)

BANK_COLUMNS = ("reference", "payer", "date", "amount", "currency", "cleared")


_TRUE = {"true", "yes", "y", "1", "cleared"}


_FALSE = {"false", "no", "n", "0", "pending", "uncleared"}


_receipts = TypeAdapter(list[BankReceipt])


def parse_bank_csv(data: bytes) -> list[BankReceipt]:
    """Columns: reference, payer, date (YYYY-MM-DD), amount, currency, cleared, and optionally
    proof_reference. Every row is checked; one bad row rejects the file."""
    limit = get_settings().pod_bank_csv_max_bytes
    if len(data) > limit:
        raise SnapshotTooLargeError(f"Bank statements can be at most {limit // 1024} KB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SnapshotInvalidError("The statement must be a UTF-8 CSV file.") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = {(h or "").strip().lower() for h in reader.fieldnames or []}
    missing = [c for c in BANK_COLUMNS if c not in headers]
    if missing:
        raise SnapshotInvalidError(f"Missing column(s): {', '.join(missing)}.")

    rows: list[dict[str, Any]] = []
    for line, row in enumerate(reader, start=2):
        values = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(values.values()):
            continue
        cleared = values["cleared"].lower()
        if cleared not in _TRUE | _FALSE:
            raise SnapshotInvalidError(f"Line {line}: cleared must be yes or no.")
        try:
            amount = Decimal(values["amount"].replace(",", ""))
        except InvalidOperation as exc:
            raise SnapshotInvalidError(f"Line {line}: amount is not a number.") from exc
        rows.append(
            {
                "reference": values["reference"],
                "payer": values["payer"],
                "date": values["date"],
                "amount": amount,
                "currency": values["currency"].upper(),
                "cleared": cleared in _TRUE,
                "proof_reference": values.get("proof_reference") or None,
            }
        )
        if len(rows) > get_settings().pod_max_rows_per_collection:
            raise SnapshotInvalidError("The statement has too many rows.")
    if not rows:
        raise SnapshotInvalidError("The statement has no rows.")
    try:
        return _receipts.validate_python(rows)
    except ValidationError as exc:
        raise SnapshotInvalidError(validation_message(exc)) from exc


def with_bank_receipts(parent: SnapshotDocument, receipts: list[BankReceipt]) -> SnapshotDocument:
    """The parent's content plus the statement's receipts. A reference already present must
    be identical: a statement can't silently change a receipt an earlier one recorded."""
    merged = {r.reference: r for r in parent.bank_receipts or []}
    for receipt in receipts:
        if receipt.currency != parent.currency:
            raise SnapshotInvalidError(
                f"Receipt {receipt.reference} is in {receipt.currency}; the snapshot is in "
                f"{parent.currency}."
            )
        known = merged.get(receipt.reference)
        if known is not None and known != receipt:
            raise SnapshotInvalidError(
                f"Receipt {receipt.reference} differs from the one already recorded."
            )
        merged[receipt.reference] = receipt
    data = parent.model_dump(mode="python")
    data["bank_receipts"] = [r.model_dump(mode="python") for r in merged.values()]
    try:
        return SnapshotDocument.model_validate(data)
    except ValidationError as exc:
        raise SnapshotInvalidError(validation_message(exc)) from exc
