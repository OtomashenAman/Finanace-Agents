"""Turn source files and connected companies into SnapshotDocuments. Nothing here writes to a
source, and nothing missing is invented: absent data stays absent and shows in coverage."""

import csv
import io
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.data_sources.models import DataSource, FinanceRecord, IntegrationEnvironment
from src.app.data_sources.records import RECORD_MODELS, RecordType
from src.app.data_sources.records import Account as QbAccount
from src.app.data_sources.records import Customer as QbCustomer
from src.app.data_sources.records import Invoice as QbInvoice
from src.app.data_sources.records import Payment as QbPayment
from src.app.service_pod.snapshots.contract import (
    Account,
    AccountClass,
    Allocation,
    BankReceipt,
    Basis,
    Customer,
    Invoice,
    Payment,
    Provenance,
    SnapshotDocument,
)
from src.app.service_pod.snapshots.exceptions import SnapshotInvalidError, SnapshotTooLargeError

MAX_REPORTED_ERRORS = 5


def _validation_message(exc: ValidationError) -> str:
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
        raise SnapshotInvalidError(_validation_message(exc)) from exc
    check_row_limits(doc)
    return doc


# --- bank statement CSV ---------------------------------------------------------------

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
        raise SnapshotInvalidError(_validation_message(exc)) from exc


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
        raise SnapshotInvalidError(_validation_message(exc)) from exc


# --- QuickBooks Online (read-only copy of synced records) -----------------------------

_QB_CLASSES = {
    "income": AccountClass.INCOME,
    "other income": AccountClass.OTHER_INCOME,
    "cost of goods sold": AccountClass.COST_OF_GOODS_SOLD,
    "expense": AccountClass.EXPENSE,
    "other expense": AccountClass.OTHER_EXPENSE,
    "bank": AccountClass.ASSET,
    "accounts receivable": AccountClass.ASSET,
    "other current asset": AccountClass.ASSET,
    "fixed asset": AccountClass.ASSET,
    "other asset": AccountClass.ASSET,
    "accounts payable": AccountClass.LIABILITY,
    "credit card": AccountClass.LIABILITY,
    "other current liability": AccountClass.LIABILITY,
    "long term liability": AccountClass.LIABILITY,
    "equity": AccountClass.EQUITY,
}


async def _records(session: AsyncSession, source: DataSource, record_type: RecordType) -> list[Any]:
    model = RECORD_MODELS[record_type]
    rows = await session.scalars(
        select(FinanceRecord.data)
        .where(FinanceRecord.source_id == source.id, FinanceRecord.record_type == record_type)
        .order_by(FinanceRecord.reference)
    )
    return [model.model_validate(data) for data in rows]


def _email(value: str | None) -> str | None:
    # QuickBooks allows free text here; only a well-formed address can be a verified contact
    if value and "@" in value and " " not in value.strip():
        return value.strip()
    return None


async def from_quickbooks(
    session: AsyncSession, source: DataSource, entity_code: str, currency: str, basis: Basis
) -> SnapshotDocument:
    """Customers, open invoices, payments and the chart of accounts as last synced. The
    other collections (GL, bank, cash position...) aren't available from this source."""
    customers: list[QbCustomer] = await _records(session, source, RecordType.CUSTOMER)
    invoices: list[QbInvoice] = await _records(session, source, RecordType.INVOICE)
    payments: list[QbPayment] = await _records(session, source, RecordType.PAYMENT)
    accounts: list[QbAccount] = await _records(session, source, RecordType.ACCOUNT)

    customer_ids = {c.name.lower(): c.external_id for c in customers}
    problems: list[str] = []

    def customer_id(name: str, what: str) -> str:
        found = customer_ids.get(name.lower())
        if found is None:
            problems.append(f"{what}: customer {name!r} isn't in the customer list")
            return ""
        return found

    pod_invoices = []
    for inv in invoices:
        if inv.invoice_date is None or inv.due_date is None or inv.balance is None:
            problems.append(f"invoice {inv.doc_number}: date, due date or balance missing")
            continue
        pod_invoices.append(
            Invoice(
                id=inv.external_id,
                number=inv.doc_number,
                customer_id=customer_id(inv.customer_name, f"invoice {inv.doc_number}"),
                txn_date=inv.invoice_date,
                due_date=inv.due_date,
                original_amount=inv.total,
                balance=inv.balance,
            )
        )
    invoice_ids = {i.number.lower(): i.id for i in pod_invoices}

    pod_payments = []
    for pay in payments:
        if pay.payment_date is None:
            problems.append(f"payment {pay.reference_number}: date missing")
            continue
        allocations = []
        if pay.invoice_number and pay.applied_amount:
            target = invoice_ids.get(pay.invoice_number.lower())
            if target is not None:
                allocations.append(Allocation(invoice_id=target, amount=pay.applied_amount))
        pod_payments.append(
            Payment(
                id=pay.external_id,
                customer_id=customer_id(pay.customer_name, f"payment {pay.reference_number}"),
                date=pay.payment_date,
                amount=pay.total,
                currency=currency,
                reference=pay.reference_number,
                allocations=allocations,
            )
        )
    if problems:
        shown = "; ".join(problems[:MAX_REPORTED_ERRORS])
        more = len(problems) - MAX_REPORTED_ERRORS
        raise SnapshotInvalidError(shown + (f" (and {more} more)" if more > 0 else ""))

    synced = source.last_synced_at
    try:
        doc = SnapshotDocument(
            provenance=(
                Provenance.SYNTHETIC_DEMO
                if source.environment == IntegrationEnvironment.SANDBOX
                else Provenance.QUICKBOOKS_READONLY_EXPORT
            ),
            company_id=source.external_id or str(source.id),
            company_name=source.name,
            entity=entity_code,
            currency=currency,
            basis=basis,
            as_of=(synced or utcnow()).date(),
            source_reference=(
                f"QuickBooks Online company {source.external_id} as synced "
                f"{synced.isoformat() if synced else 'never'}"
            ),
            customers=[
                Customer(id=c.external_id, name=c.name, email=_email(c.email)) for c in customers
            ],
            invoices=pod_invoices,
            payments=pod_payments,
            accounts=[
                Account(
                    id=a.external_id,
                    name=a.name,
                    number=a.number,
                    classification=_QB_CLASSES[(a.account_type or "").lower()],
                )
                for a in accounts
                if (a.account_type or "").lower() in _QB_CLASSES
            ],
        )
    except ValidationError as exc:
        raise SnapshotInvalidError(_validation_message(exc)) from exc
    check_row_limits(doc)
    return doc
