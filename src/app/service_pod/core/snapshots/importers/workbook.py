"""A normalized export as an Excel workbook: one sheet per collection, plus a Company sheet.

The same contract as the JSON export, in a form people can open and edit. A sheet that isn't
in the file is a collection the source doesn't supply; a sheet with only its header row is
"supplied, nothing there". Every row goes through the same checks as JSON (and the same
cross-references), and errors name the sheet and row.

Sheets (names and headers are matched case- and punctuation-insensitively):

    Company           Company ID, Company Name, Entity, Currency, Basis, As of, Provenance,
                      Source reference                                   (one data row)
    Customers         ID, Name, Email, Contact
    Invoices          ID, Number, Customer ID, Date, Due Date, Amount, Balance, Terms, Document
    Payments          ID, Customer ID, Date, Amount, Currency, Reference, Invoice ID, Applied
                      (one row per invoice a payment is applied to; repeat the payment columns)
    Accounts          ID, Name, Number, Classification
    GL lines          ID, Account ID, Period, Amount, Report ID, Transaction IDs
    Transactions      ID, Date, Period, Type, Counterparty, Account ID, Amount, Tax, Status,
                      GL Line ID, Document, Entity
    Bank receipts     Reference, Payer, Date, Amount, Currency, Cleared, Proof
    Contracts         ID, Customer ID, Invoice IDs, Terms, Status
    Planned outflows  ID, Date, Amount, Category, Approved, Approval Ref
    Cash position     As of, Bank balance, QuickBooks cash, Reconciliation balance,
                      Policy buffer, Cleared, Proof                       (one data row)
    Balance sheets    Period, Assets, Liabilities, Equity, Report ID
    Close status      Period, Status, Required checks

Lists (Transaction IDs, Invoice IDs, Required checks) are separated by commas or semicolons.
"""

import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import load_workbook
from pydantic import ValidationError

from src.app.common.text_extraction.base import ExtractionError, check_zip_archive
from src.app.service_pod.core.snapshots.contract import Collection, SnapshotDocument
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError
from src.app.service_pod.core.snapshots.importers.base import (
    MAX_REPORTED_ERRORS,
    check_row_limits,
)

# sheet -> (collection or "company", {header: field})
_COMPANY = {
    "companyid": "company_id",
    "companyname": "company_name",
    "entity": "entity",
    "currency": "currency",
    "basis": "basis",
    "asof": "as_of",
    "provenance": "provenance",
    "sourcereference": "source_reference",
}
_SHEETS: dict[str, tuple[str, dict[str, str]]] = {
    "company": ("company", _COMPANY),
    "customers": (
        Collection.CUSTOMERS,
        {"id": "id", "name": "name", "email": "email", "contact": "contact_name"},
    ),
    "invoices": (
        Collection.INVOICES,
        {
            "id": "id",
            "number": "number",
            "customerid": "customer_id",
            "date": "txn_date",
            "duedate": "due_date",
            "amount": "original_amount",
            "balance": "balance",
            "terms": "terms",
            "document": "document_ref",
        },
    ),
    "payments": (
        Collection.PAYMENTS,
        {
            "id": "id",
            "customerid": "customer_id",
            "date": "date",
            "amount": "amount",
            "currency": "currency",
            "reference": "reference",
            "invoiceid": "invoice_id",
            "applied": "applied",
        },
    ),
    "accounts": (
        Collection.ACCOUNTS,
        {"id": "id", "name": "name", "number": "number", "classification": "classification"},
    ),
    "gllines": (
        Collection.GL_LINES,
        {
            "id": "id",
            "accountid": "account_id",
            "period": "period",
            "amount": "amount",
            "reportid": "report_id",
            "transactionids": "transaction_ids",
        },
    ),
    "transactions": (
        Collection.TRANSACTIONS,
        {
            "id": "id",
            "date": "date",
            "period": "period",
            "type": "type",
            "counterparty": "counterparty",
            "accountid": "account_id",
            "amount": "amount",
            "tax": "tax",
            "status": "status",
            "gllineid": "gl_line_id",
            "document": "document_ref",
            "entity": "entity",
        },
    ),
    "bankreceipts": (
        Collection.BANK_RECEIPTS,
        {
            "reference": "reference",
            "payer": "payer",
            "date": "date",
            "amount": "amount",
            "currency": "currency",
            "cleared": "cleared",
            "proof": "proof_reference",
        },
    ),
    "contracts": (
        Collection.CONTRACTS,
        {
            "id": "id",
            "customerid": "customer_id",
            "invoiceids": "invoice_ids",
            "terms": "terms",
            "status": "status",
        },
    ),
    "plannedoutflows": (
        Collection.PLANNED_OUTFLOWS,
        {
            "id": "id",
            "date": "date",
            "amount": "amount",
            "category": "category",
            "approved": "approved",
            "approvalref": "approval_ref",
        },
    ),
    "cashposition": (
        Collection.CASH_POSITION,
        {
            "asof": "as_of",
            "bankbalance": "bank_balance",
            "quickbookscash": "quickbooks_cash_balance",
            "reconciliationbalance": "reconciliation_balance",
            "policybuffer": "policy_buffer",
            "cleared": "cleared",
            "proof": "proof_reference",
        },
    ),
    "balancesheets": (
        Collection.BALANCE_SHEETS,
        {
            "period": "period",
            "assets": "assets",
            "liabilities": "liabilities",
            "equity": "equity",
            "reportid": "report_id",
        },
    ),
    "closestatus": (
        Collection.CLOSE_STATUS,
        {"period": "period", "status": "status", "requiredchecks": "required_checks"},
    ),
}
_LISTS = {"transaction_ids", "invoice_ids", "required_checks"}
_PERIODS = {"period"}
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def _key(text: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _value(field: str, raw: object) -> Any:
    """An Excel cell as the contract expects it (dates stay dates, codes stay text)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [] if field in _LISTS else None
    if field in _PERIODS and isinstance(raw, datetime | date):
        return raw.strftime("%Y-%m")  # Excel turned "2026-09" into a date
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        number = Decimal(str(raw))
        # IDs and codes typed as numbers (80000001) stay text without ".0"
        return number if field not in {"id", "number", "reference"} else str(int(raw))
    text = str(raw).strip()
    if field in _LISTS:
        return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]
    if field in {"cleared", "approved"} and text.lower() in _TRUE | _FALSE:
        return text.lower() in _TRUE
    return text


def _rows(sheet: Any, title: str, columns: dict[str, str]) -> list[tuple[int, dict[str, Any]]]:
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        raise SnapshotInvalidError(f"Sheet '{title}' is empty: it needs its header row.")
    fields: list[str | None] = []
    for cell in header:
        key = _key(cell)
        if not key:
            fields.append(None)
        elif key in columns:
            fields.append(columns[key])
        else:
            raise SnapshotInvalidError(f"Sheet '{title}': unknown column '{cell}'.")
    out = []
    for number, row in enumerate(rows, start=2):
        values = {f: _value(f, v) for f, v in zip(fields, row, strict=False) if f is not None}
        if any(v not in (None, []) for v in values.values()):
            out.append((number, {k: v for k, v in values.items() if v is not None}))
    return out


def _payments(rows: list[tuple[int, dict[str, Any]]], title: str) -> list[dict[str, Any]]:
    """One row per (payment, invoice applied); the payment's own columns repeat."""
    payments: dict[str, dict[str, Any]] = {}
    for number, row in rows:
        invoice, applied = row.pop("invoice_id", None), row.pop("applied", None)
        known = payments.get(str(row.get("id")))
        if known is None:
            known = payments[str(row.get("id"))] = {**row, "allocations": []}
        elif any(known.get(k) != v for k, v in row.items()):
            raise SnapshotInvalidError(
                f"Sheet '{title}' row {number}: payment {row.get('id')} repeats with "
                "different details."
            )
        if invoice is not None or applied is not None:
            known["allocations"].append({"invoice_id": invoice, "amount": applied})
    return list(payments.values())


def _where(exc: ValidationError, titles: dict[str, str], row_numbers: dict[str, list[int]]) -> str:
    """Validation errors named by sheet and Excel row instead of list positions."""
    parts = []
    for err in exc.errors()[:MAX_REPORTED_ERRORS]:
        loc = list(err["loc"])
        msg = str(err["msg"]).removeprefix("Value error, ")
        if loc and str(loc[0]) in titles:
            where = f"Sheet '{titles[str(loc[0])]}'"
            rows = row_numbers.get(str(loc[0]))
            if len(loc) > 1 and isinstance(loc[1], int):
                where += f" row {rows[loc[1]]}" if rows else f" item {loc[1] + 1}"
                loc = loc[2:]
            else:
                loc = loc[1:]
            field = ".".join(str(p) for p in loc)
            parts.append(f"{where}{', ' + field if field else ''}: {msg}")
        else:
            field = ".".join(str(p) for p in loc)
            parts.append(f"{'Company sheet, ' + field + ': ' if field else ''}{msg}")
    more = len(exc.errors()) - MAX_REPORTED_ERRORS
    return "; ".join(parts) + (f" (and {more} more)" if more > 0 else "")


def parse_workbook(data: bytes, filename: str) -> SnapshotDocument:
    if not filename.lower().endswith(".xlsx"):
        raise SnapshotInvalidError("Upload an .xlsx workbook.")
    try:
        check_zip_archive(data, "XLSX")
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ExtractionError as exc:
        raise SnapshotInvalidError(str(exc)) from exc
    except Exception as exc:  # openpyxl raises many types for broken files
        raise SnapshotInvalidError("This XLSX file is damaged and can't be read.") from exc

    doc: dict[str, Any] = {}
    titles: dict[str, str] = {}  # collection -> sheet title
    row_numbers: dict[str, list[int]] = {}  # collection -> Excel row of each item
    try:
        for sheet in workbook.worksheets:
            entry = _SHEETS.get(_key(sheet.title))
            if entry is None:
                raise SnapshotInvalidError(
                    f"Unknown sheet '{sheet.title}': use Company, Customers, Invoices, "
                    "Payments, Accounts, GL lines, Transactions, Bank receipts, Contracts, "
                    "Planned outflows, Cash position, Balance sheets or Close status."
                )
            target, columns = entry
            if target in titles:
                raise SnapshotInvalidError(f"Sheet '{sheet.title}' appears twice.")
            titles[target] = sheet.title
            rows = _rows(sheet, sheet.title, columns)
            if target in ("company", Collection.CASH_POSITION):
                if len(rows) != 1:
                    raise SnapshotInvalidError(f"Sheet '{sheet.title}' needs exactly one row.")
                if target == "company":
                    doc.update(rows[0][1])
                else:
                    doc[target] = rows[0][1]
            elif target == Collection.PAYMENTS:
                doc[target] = _payments(rows, sheet.title)
            else:
                doc[target] = [row for _, row in rows]
                row_numbers[target] = [n for n, _ in rows]
    finally:
        workbook.close()
    if "company" not in titles:
        raise SnapshotInvalidError("The workbook needs a Company sheet.")
    doc.setdefault("source_reference", f"Excel workbook {filename}")
    try:
        result = SnapshotDocument.model_validate(doc)
    except ValidationError as exc:
        raise SnapshotInvalidError(_where(exc, titles, row_numbers)) from exc
    check_row_limits(result)
    return result
