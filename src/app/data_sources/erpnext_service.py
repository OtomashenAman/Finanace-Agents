"""ERPNext connections: an API user's key and secret for one site and company, private to
the person who connects it (like a QuickBooks connection). The secret is encrypted at rest
and never returned.

Sync brings the same canonical records a QuickBooks sync does (vendors, supplier invoices as
bills, purchase orders, accounts) into finance_records, for the data sources page and the
agents' prefill. The Finance POD doesn't use them: it freezes a fuller snapshot straight from
the site (service_pod snapshots, importers/erpnext.py).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.data_sources import crypto
from src.app.data_sources.models import DataSource, SourceKind, SourceStatus
from src.app.data_sources.providers import erpnext
from src.app.data_sources.records import Account, Bill, PurchaseOrder, Record, RecordType, Vendor
from src.app.data_sources.schemas import DataSourceOut, ErpNextConnect

SYNC_DAYS = 400  # purchase orders and supplier invoices this recent


class ErpNextConnectionError(AppError):
    status_code = 422
    code = "erpnext_connection_failed"


def credentials(source: DataSource) -> erpnext.Credentials:
    if source.kind != SourceKind.ERPNEXT or not (
        source.base_url and source.client_id and source.client_secret_enc
    ):
        raise ErpNextConnectionError("This isn't a usable ERPNext connection.")
    try:
        secret = crypto.decrypt(source.client_secret_enc)
    except ValueError as exc:
        raise ErpNextConnectionError(
            "The stored API secret can't be read any more; enter it again."
        ) from exc
    return erpnext.Credentials(source.base_url, source.client_id, secret)


@asynccontextmanager
async def erpnext_api(source: DataSource) -> AsyncIterator[erpnext.Api]:
    async with erpnext.api(credentials(source)) as api:
        yield api


async def _check(api: erpnext.Api, company: str) -> str:
    """The API user, once the key works and the company exists (raises with the reason)."""
    try:
        user = await api.whoami()
    except erpnext.ErpNextError as exc:
        # Not reached, or the key refused: the company name isn't the problem yet
        raise ErpNextConnectionError(str(exc)) from exc
    try:
        await api.get("Company", company)
    except erpnext.ErpNextAuthError as exc:
        raise ErpNextConnectionError(str(exc)) from exc
    except erpnext.ErpNextError as exc:
        raise ErpNextConnectionError(f"{exc} (is {company!r} the company's exact name?)") from exc
    return user


async def connect(
    session: AsyncSession, user: User, body: ErpNextConnect, ctx: RequestContext
) -> DataSourceOut:
    try:
        base_url = erpnext.check_base_url(body.base_url)
    except erpnext.ErpNextError as exc:
        raise ErpNextConnectionError(str(exc)) from exc
    creds = erpnext.Credentials(base_url, body.api_key.strip(), body.api_secret.strip())
    async with erpnext.api(creds) as api:
        api_user = await _check(api, body.company.strip())
    source = DataSource(
        owner_id=user.id,
        kind=SourceKind.ERPNEXT,
        name=body.name.strip(),
        status=SourceStatus.CONNECTED,
        base_url=base_url,
        client_id=creds.api_key,
        client_secret_enc=crypto.encrypt(creds.api_secret),
        environment=body.environment,
        external_id=body.company.strip(),
        last_synced_at=utcnow(),
        record_counts={},
    )
    session.add(source)
    await session.flush()
    record_event(
        session,
        "data_source.connected",
        ctx,
        actor_id=user.id,
        source_id=str(source.id),
        kind=SourceKind.ERPNEXT.value,
        name=source.name,
        base_url=base_url,
        company=source.external_id,
        api_user=api_user,
        summary=f"Connected ERPNext {base_url} (company {source.external_id})",
    )
    await session.commit()
    await session.refresh(source)
    return DataSourceOut.model_validate(source)


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _day(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _vendor(row: dict[str, Any], email: dict[str, str]) -> Vendor:
    return Vendor(
        external_id=row["name"],
        name=row.get("supplier_name") or row["name"],
        email=email.get(row["name"]),
        tax_id=row.get("tax_id") or None,
        active=not row.get("disabled"),
    )


def _account(row: dict[str, Any]) -> Account:
    return Account(
        external_id=row["name"],
        number=row.get("account_number") or None,
        name=row["name"],
        account_type=row.get("account_type") or row.get("root_type"),
    )


def _order(doc: dict[str, Any]) -> PurchaseOrder:
    received = sum(
        (Decimal(str(i.get("received_qty") or 0)) * Decimal(str(i.get("rate") or 0))
         for i in doc.get("items", [])),
        Decimal(0),
    )  # fmt: skip
    return PurchaseOrder(
        external_id=doc["name"],
        po_number=doc["name"],
        vendor_name=doc["supplier"],
        total=_money(doc.get("grand_total")),
        received_amount=_money(received),
        status=(doc.get("status") or "")[:50] or None,
        po_date=_day(doc.get("transaction_date")),
    )


def _bill(doc: dict[str, Any]) -> Bill:
    lines = doc.get("items", [])
    return Bill(
        external_id=doc["name"],
        doc_number=doc.get("bill_no") or doc["name"],
        vendor_name=doc["supplier"],
        total=_money(doc.get("grand_total")),
        tax_total=_money(doc.get("total_taxes_and_charges")) or None,
        bill_date=_day(doc.get("bill_date") or doc.get("posting_date")),
        due_date=_day(doc.get("due_date")),
        po_number=next((i["purchase_order"] for i in lines if i.get("purchase_order")), None),
        account=next((i["expense_account"][:100] for i in lines if i.get("expense_account")), None),
        balance=_money(doc.get("outstanding_amount")),
    )


async def _documents(
    api: erpnext.Api, doctype: str, filters: list[list[Any]]
) -> list[dict[str, Any]]:
    names = [r["name"] for r in await api.rows(doctype, ["name"], filters)]
    return await api.get_many(doctype, names)


async def fetch_records(source: DataSource) -> tuple[dict[RecordType, list[Record]], int]:
    """(canonical records by type, rows skipped because they don't fit). Raises
    ErpNextConnectionError when the site can't be read."""
    company = source.external_id or ""
    since = (utcnow().date() - timedelta(days=SYNC_DAYS)).isoformat()
    window: list[list[Any]] = [["company", "=", company], ["docstatus", "<", 2]]
    try:
        async with erpnext_api(source) as api:
            await _check(api, company)
            suppliers = await api.rows("Supplier", ["name", "supplier_name", "tax_id", "disabled"])
            contacts = await api.rows(
                "Contact",
                ["email_id", "`tabDynamic Link`.link_name"],
                [["Dynamic Link", "link_doctype", "=", "Supplier"]],
                order_by="is_primary_contact desc",
            )
            accounts = await api.rows(
                "Account",
                ["name", "account_name", "account_number", "account_type", "root_type"],
                [["company", "=", company], ["is_group", "=", 0]],
            )
            orders = await _documents(
                api, "Purchase Order", [*window, ["transaction_date", ">=", since]]
            )
            bills = await _documents(
                api, "Purchase Invoice", [*window, ["posting_date", ">=", since]]
            )
    except erpnext.ErpNextError as exc:
        raise ErpNextConnectionError(str(exc)) from exc

    email: dict[str, str] = {}
    for c in contacts:
        if c.get("email_id") and c.get("link_name"):
            email.setdefault(c["link_name"], c["email_id"])
    records: dict[RecordType, list[Record]] = {t: [] for t in (
        RecordType.VENDOR, RecordType.ACCOUNT, RecordType.PURCHASE_ORDER, RecordType.BILL
    )}  # fmt: skip
    skipped = 0

    def add(record_type: RecordType, make: Any, row: dict[str, Any]) -> None:
        nonlocal skipped
        try:
            records[record_type].append(make(row))
        except (ValueError, KeyError):  # a row that doesn't fit the canonical shape
            skipped += 1

    for row in suppliers:
        add(RecordType.VENDOR, lambda r: _vendor(r, email), row)
    for row in accounts:
        add(RecordType.ACCOUNT, _account, row)
    for doc in orders:
        add(RecordType.PURCHASE_ORDER, _order, doc)
    for doc in bills:
        add(RecordType.BILL, _bill, doc)
    return records, skipped
