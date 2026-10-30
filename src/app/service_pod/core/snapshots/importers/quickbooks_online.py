"""A frozen, read-only copy of a connected QuickBooks Online company's synced records."""

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
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
    Basis,
    Customer,
    Invoice,
    Payment,
    Provenance,
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError
from src.app.service_pod.core.snapshots.importers.base import (
    MAX_REPORTED_ERRORS,
    check_row_limits,
    validation_message,
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
        raise SnapshotInvalidError(validation_message(exc)) from exc
    check_row_limits(doc)
    return doc
