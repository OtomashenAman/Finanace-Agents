"""A frozen, read-only copy of a connected QuickBooks Online company's synced records."""

import re
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError
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
from src.app.service_pod.core.snapshots.contract import (
    Account,
    AccountClass,
    Allocation,
    BalanceSheet,
    Basis,
    CloseStatus,
    Customer,
    GlLine,
    Invoice,
    Payment,
    Provenance,
    SnapshotDocument,
    Transaction,
)
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError
from src.app.service_pod.core.snapshots.importers.base import (
    check_row_limits,
    validation_message,
)
from src.app.service_pod.core.snapshots.importers.quickbooks_pnl import (
    PnlReports,
    build_balance_sheets,
    build_close_status,
    build_pnl,
)

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
    out = []
    for data in rows:
        try:
            out.append(model.model_validate(data))
        except ValidationError:
            continue  # stored by an older version in another shape: not usable here
    return out


_EMAIL = TypeAdapter(EmailStr)


def _email(value: str | None) -> str | None:
    """QuickBooks allows free text here, often several addresses ("a@x.com, b@y.com"): the
    first well-formed one is the verified contact; none, and the customer has no email."""
    for part in re.split(r"[,;\s]+", value or ""):
        if "@" in part:
            try:
                return str(_EMAIL.validate_python(part))
            except ValidationError:
                continue
    return None


async def from_quickbooks(
    session: AsyncSession,
    source: DataSource,
    entity_code: str,
    currency: str,
    basis: Basis,
    pnl: PnlReports | None = None,
    notes: list[str] | None = None,
) -> SnapshotDocument:
    """Customers, open invoices, payments and the chart of accounts as last synced. The
    other collections (GL, bank, cash position...) aren't available from this source.

    Zero-amount payments are left out: QuickBooks uses them to apply a credit memo to an
    invoice, which moves no cash. QuickBooks data is what it is, so a record the contract
    can't take never refuses the snapshot: it is repaired where the meaning is clear (a
    duplicate invoice number, a missing due date, an over-applied payment) or left out,
    and the notes say which."""
    customers: list[QbCustomer] = await _records(session, source, RecordType.CUSTOMER)
    invoices: list[QbInvoice] = await _records(session, source, RecordType.INVOICE)
    payments: list[QbPayment] = await _records(session, source, RecordType.PAYMENT)
    accounts: list[QbAccount] = await _records(session, source, RecordType.ACCOUNT)
    limit = get_settings().pod_max_rows_per_collection
    fixed: list[str] = []  # repaired, kept
    left_out: list[str] = []  # not in the snapshot

    pod_customers: dict[str, Customer] = {}
    customer_ids: dict[str, str] = {}
    for c in customers:
        if c.external_id in pod_customers:
            continue
        try:
            pod_customers[c.external_id] = Customer(
                id=c.external_id, name=c.name, email=_email(c.email)
            )
        except ValidationError as exc:
            left_out.append(f"customer {c.name}: {validation_message(exc)}")
            continue
        customer_ids.setdefault(c.name.lower(), c.external_id)

    def customer_id(name: str) -> str:
        """Customers named on an invoice or payment but not synced are added: QuickBooks
        lists only active customers and renames a deleted one "<name> (deleted)", and its
        invoices are still owed."""
        found = customer_ids.get(name.lower())
        if found is None:
            found = f"unlisted:{name.lower()}"[:100]
            pod_customers[found] = Customer(id=found, name=name)
            customer_ids[name.lower()] = found
            fixed.append(
                f"customer {name} isn't in the QuickBooks customer list (inactive or "
                "deleted): kept with its invoices and payments, no email on file"
            )
        return found

    # Open invoices first, then the newest, so a cut at the row limit drops old paid ones
    invoices.sort(
        key=lambda i: (
            (i.balance if i.balance is not None else i.total) <= 0,
            -(i.invoice_date or i.due_date or date.min).toordinal(),
        )
    )
    pod_invoices: list[Invoice] = []
    invoice_ids: dict[str, str] = {}  # number as QuickBooks shows it -> id (the first one)
    numbers: set[str] = set()
    invoice_seen: set[str] = set()
    for inv in invoices:
        what = f"invoice {inv.doc_number}"
        if len(pod_invoices) >= limit:
            left_out.append(f"invoices beyond the newest {limit}")
            break
        if inv.external_id in invoice_seen:
            continue
        txn_date = inv.invoice_date or inv.due_date
        if txn_date is None:
            left_out.append(f"{what}: no date")
            continue
        if inv.total < 0:
            left_out.append(f"{what}: negative amount")
            continue
        due = inv.due_date or txn_date
        balance = inv.balance
        if balance is None:
            balance = Decimal(0) if inv.paid_date else inv.total
        if balance < 0 or balance > inv.total:
            fixed.append(f"{what}: balance {balance} outside 0..{inv.total}, capped")
            balance = min(max(balance, Decimal(0)), inv.total)
        number = inv.doc_number
        if number.lower() in numbers:  # QuickBooks allows the same number twice
            number = f"{inv.doc_number} ({inv.external_id})"[:100]
            fixed.append(f"{what}: number used twice in QuickBooks, shown as {number}")
        try:
            pod_invoices.append(
                Invoice(
                    id=inv.external_id,
                    number=number,
                    customer_id=customer_id(inv.customer_name),
                    txn_date=txn_date,
                    due_date=due,
                    original_amount=inv.total,
                    balance=balance,
                )
            )
        except ValidationError as exc:
            left_out.append(f"{what}: {validation_message(exc)}")
            continue
        numbers.add(number.lower())
        invoice_seen.add(inv.external_id)
        invoice_ids.setdefault(inv.doc_number.lower(), inv.external_id)

    payments.sort(key=lambda p: -(p.payment_date or date.min).toordinal())
    pod_payments: list[Payment] = []
    payment_ids: set[str] = set()
    for pay in payments:
        what = f"payment {pay.reference_number}"
        if pay.total <= 0 or pay.external_id in payment_ids:
            continue  # a credit memo applied to an invoice: no cash moved
        if len(pod_payments) >= limit:
            left_out.append(f"payments beyond the newest {limit}")
            break
        if pay.payment_date is None:
            left_out.append(f"{what}: no date")
            continue
        try:
            allocations = []
            if pay.invoice_number and pay.applied_amount and pay.applied_amount > 0:
                target = invoice_ids.get(pay.invoice_number.lower())
                if target is not None:
                    amount = min(pay.applied_amount, pay.total)
                    allocations.append(Allocation(invoice_id=target, amount=amount))
            pod_payments.append(
                Payment(
                    id=pay.external_id,
                    customer_id=customer_id(pay.customer_name),
                    date=pay.payment_date,
                    amount=pay.total,
                    currency=currency,
                    reference=pay.reference_number,
                    allocations=allocations,
                )
            )
        except ValidationError as exc:
            left_out.append(f"{what}: {validation_message(exc)}")
            continue
        payment_ids.add(pay.external_id)

    pod_accounts: dict[str, Account] = {}
    for a in accounts:
        kind = (a.account_type or "").lower()
        if kind not in _QB_CLASSES or a.external_id in pod_accounts:
            continue
        try:
            pod_accounts[a.external_id] = Account(
                id=a.external_id, name=a.name, number=a.number, classification=_QB_CLASSES[kind]
            )
        except ValidationError as exc:
            left_out.append(f"account {a.name}: {validation_message(exc)}")

    if notes is not None:
        notes.extend(_summary("Repaired from QuickBooks", fixed))
        notes.extend(_summary("Left out of the snapshot", left_out))
    return _document(
        source,
        entity_code,
        currency,
        basis,
        list(pod_customers.values()),
        pod_invoices,
        pod_payments,
        list(pod_accounts.values()),
        pnl,
        notes,
    )


def _summary(title: str, items: list[str], shown: int = 10) -> list[str]:
    if not items:
        return []
    unique = list(dict.fromkeys(items))
    more = len(unique) - shown
    return [
        f"{title} ({len(unique)}): "
        + "; ".join(unique[:shown])
        + (f" (and {more} more)" if more > 0 else "")
    ]


def _document(
    source: DataSource,
    entity_code: str,
    currency: str,
    basis: Basis,
    customers: list[Customer],
    invoices: list[Invoice],
    payments: list[Payment],
    accounts: list[Account],
    pnl: PnlReports | None,
    notes: list[str] | None,
) -> SnapshotDocument:
    gl_lines: list[GlLine] | None = None
    transactions: list[Transaction] | None = None
    balance_sheets: list[BalanceSheet] | None = None
    close_status: list[CloseStatus] | None = None
    pnl_notes: list[str] = []
    if pnl is not None:
        # P&L evidence (FP&A): only when the reports were read; otherwise not supplied
        try:
            gl_lines, transactions, pnl_notes = build_pnl(
                pnl,
                {a.id: a.classification for a in accounts},
                {a.name.strip().lower(): a.id for a in accounts},
            )
            balance_sheets = build_balance_sheets(pnl)
            close_status = build_close_status(pnl)
        except (ValidationError, ValueError, KeyError) as exc:
            gl_lines = transactions = balance_sheets = close_status = None
            pnl_notes = [f"The P&L detail couldn't be used, so FP&A evidence is missing: {exc}"]

    synced = source.last_synced_at
    common: dict[str, Any] = {
        "provenance": (
            Provenance.SYNTHETIC_DEMO
            if source.environment == IntegrationEnvironment.SANDBOX
            else Provenance.QUICKBOOKS_READONLY_EXPORT
        ),
        "company_id": source.external_id or str(source.id),
        "company_name": source.name,
        "entity": entity_code,
        "currency": currency,
        "basis": basis,
        "as_of": (synced or utcnow()).date(),
        "source_reference": (
            f"QuickBooks Online company {source.external_id} as synced "
            f"{synced.isoformat() if synced else 'never'}"
        ),
        "customers": customers,
        "invoices": invoices,
        "payments": payments,
        "accounts": accounts,
    }
    try:
        doc = SnapshotDocument(
            **common,
            gl_lines=gl_lines,
            transactions=transactions,
            balance_sheets=balance_sheets,
            close_status=close_status,
        )
    except ValidationError as exc:
        if gl_lines is None and transactions is None and balance_sheets is None:
            raise SnapshotInvalidError(validation_message(exc)) from exc
        # The receivables are what matter here: keep them, without the P&L detail
        try:
            doc = SnapshotDocument(**common)
        except ValidationError as again:
            raise SnapshotInvalidError(validation_message(again)) from again
        pnl_notes = [
            "The P&L detail couldn't be used, so FP&A evidence is missing: "
            + validation_message(exc)
        ]
    if notes is not None:
        notes.extend(pnl_notes)
    check_row_limits(doc)
    return doc
