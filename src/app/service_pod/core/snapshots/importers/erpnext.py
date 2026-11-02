"""ERPNext -> SnapshotDocument: the Procure-to-Pay collections, read live over the REST API.

Nothing is written. Masters come whole; purchase documents (requests, quotations, orders,
receipts, supplier invoices) from the last READ_DAYS, cancelled ones left out. A link to a
document outside that window (e.g. a receipt for an old order) is dropped rather than broken:
the snapshot only cites what it contains.

ERPNext's lab is the "Lab" accounting dimension (field `lab`), a grant is a Project (with
the custom grant fields when the site has them), a department is a cost centre.
"""

import hashlib
import html
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from pydantic import EmailStr, TypeAdapter, ValidationError

from src.app.data_sources.providers.erpnext import Api
from src.app.service_pod.core.snapshots.contract import (
    Account,
    AccountClass,
    Basis,
    Bill,
    BillLine,
    Budget,
    BudgetActual,
    CostCentre,
    Grant,
    Item,
    ItemPrice,
    Lab,
    OrderLine,
    Provenance,
    PurchaseOrder,
    PurchaseReceipt,
    PurchaseRequest,
    QuotationLine,
    ReceiptLine,
    RequestLine,
    SnapshotDocument,
    SupplierQuotation,
    Vendor,
    VendorContract,
)
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError
from src.app.service_pod.core.snapshots.importers.base import check_row_limits, validation_message

READ_DAYS = 400
LAB_FIELD = "lab"
DOC_STATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
_EMAIL = TypeAdapter(EmailStr)
_CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENT)


def qty(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


def _date(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _text(value: Any, limit: int = 4000) -> str | None:
    if not value:
        return None
    plain = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
    return re.sub(r"\s+", " ", plain).strip()[:limit] or None


def _email(value: Any) -> str | None:
    try:
        return str(_EMAIL.validate_python(value)) if value else None
    except ValidationError:
        return None


def _classification(row: dict[str, Any]) -> AccountClass:
    if row.get("account_type") == "Cost of Goods Sold":
        return AccountClass.COST_OF_GOODS_SOLD
    return {
        "Asset": AccountClass.ASSET,
        "Liability": AccountClass.LIABILITY,
        "Equity": AccountClass.EQUITY,
        "Income": AccountClass.INCOME,
    }.get(row.get("root_type") or "", AccountClass.EXPENSE)


def _coding(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_centre_id": line.get("cost_center") or None,
        "lab_id": line.get(LAB_FIELD) or None,
        "grant_id": line.get("project") or None,
        "account_id": line.get("expense_account") or None,
    }


async def _vendors(api: Api) -> list[Vendor]:
    rows = await api.rows(
        "Supplier", ["name", "supplier_name", "supplier_group", "tax_id", "disabled", "on_hold"]
    )
    contacts = await api.rows(
        "Contact",
        ["email_id", "is_primary_contact", "`tabDynamic Link`.link_name"],
        [["Dynamic Link", "link_doctype", "=", "Supplier"]],
        order_by="is_primary_contact desc",
    )
    email: dict[str, str] = {}
    for c in contacts:
        address = _email(c.get("email_id"))
        if address and c.get("link_name") and c["link_name"] not in email:
            email[c["link_name"]] = address
    banks: dict[str, list[str]] = defaultdict(list)
    for b in await api.rows(
        "Bank Account",
        ["party", "bank", "bank_account_no", "iban", "branch_code"],
        [["party_type", "=", "Supplier"]],
    ):
        banks[b["party"]].append(
            "|".join(
                str(b.get(k) or "") for k in ("bank", "bank_account_no", "iban", "branch_code")
            )
        )
    return [
        Vendor(
            id=r["name"],
            name=r["supplier_name"] or r["name"],
            group=r.get("supplier_group") or None,
            email=email.get(r["name"]),
            tax_id=(r.get("tax_id") or None),
            status="Disabled" if r.get("disabled") else "On hold" if r.get("on_hold") else "Active",
            bank_fingerprint=(
                hashlib.sha256("\n".join(sorted(banks[r["name"]])).encode()).hexdigest()
                if banks.get(r["name"])
                else None
            ),
        )
        for r in rows
    ]


async def _items(api: Api, company: str) -> list[Item]:
    rows = await api.rows("Item", ["item_code", "item_name", "item_group", "is_stock_item"])
    defaults = await api.rows(
        "Item",
        ["item_code", "`tabItem Default`.expense_account"],
        [["Item Default", "company", "=", company]],
    )
    expense = {d["item_code"]: d.get("expense_account") for d in defaults}
    return [
        Item(
            code=r["item_code"],
            name=r.get("item_name") or r["item_code"],
            group=r.get("item_group") or "All Item Groups",
            stock_item=bool(r.get("is_stock_item")),
            expense_account_id=expense.get(r["item_code"]) or None,
        )
        for r in rows
    ]


async def _prices(api: Api, price_list: str | None) -> list[ItemPrice]:
    filters: list[list[Any]] = [["buying", "=", 1]]
    if price_list:
        filters.append(["price_list", "=", price_list])
    rows = await api.rows(
        "Item Price", ["item_code", "supplier", "price_list_rate", "currency"], filters
    )
    seen: set[tuple[str, str | None]] = set()
    out = []
    for r in rows:
        key = (r["item_code"], r.get("supplier") or None)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ItemPrice(
                item_code=r["item_code"],
                vendor_id=r.get("supplier") or None,
                rate=Decimal(str(r["price_list_rate"])),
                currency=r.get("currency") or "USD",
            )
        )
    return out


async def _labs(api: Api) -> list[Lab] | None:
    dims = await api.rows("Accounting Dimension", ["fieldname", "document_type", "disabled"])
    lab = next((d for d in dims if d.get("fieldname") == LAB_FIELD and not d.get("disabled")), None)
    if lab is None:
        return None
    return [
        Lab(id=r["name"], name=r["name"]) for r in await api.rows(lab["document_type"], ["name"])
    ]


def _grant(row: dict[str, Any]) -> Grant:
    groups = [g.strip() for g in str(row.get("grant_allowed_item_groups") or "").split(",")]
    return Grant(
        id=row["name"],
        name=row.get("project_name") or row["name"],
        funder=row.get("grant_funder") or None,
        start_date=_date(row.get("expected_start_date")),
        end_date=_date(row.get("expected_end_date")),
        restricted=bool(row.get("grant_restricted")),
        allowed_item_groups=[g for g in groups if g],
        status=row.get("status") or "Open",
    )


async def _budgets(api: Api, company: str) -> tuple[list[Budget], list[BudgetActual]]:
    rows = await api.rows(
        "Budget",
        ["name", "budget_against", "cost_center", "project", "account", "from_fiscal_year",
         "to_fiscal_year", "budget_amount"],
        [["company", "=", company], ["docstatus", "=", 1]],
    )  # fmt: skip
    years = {
        y["name"]: (_date(y["year_start_date"]), _date(y["year_end_date"]))
        for y in await api.rows("Fiscal Year", ["name", "year_start_date", "year_end_date"])
    }
    budgets: list[Budget] = []
    for r in rows:
        against = "cost_centre" if r["budget_against"] == "Cost Center" else "grant"
        target = r["cost_center"] if against == "cost_centre" else r["project"]
        if not target:
            continue
        fy = r["from_fiscal_year"]
        if r.get("to_fiscal_year") and r["to_fiscal_year"] != fy:
            fy = f"{fy}-{r['to_fiscal_year']}"
        budgets.append(
            Budget(id=r["name"], against=against, target_id=target, account_id=r["account"],
                   fiscal_year=fy, amount=money(r["budget_amount"]))
        )  # fmt: skip
    if not budgets:
        return budgets, []
    accounts = sorted({b.account_id for b in budgets})
    spans = [years[y] for b in budgets for y in b.fiscal_year.split("-") if y in years]
    start = min(s for s, _ in spans if s)
    end = max(e for _, e in spans if e)
    entries = await api.rows(
        "GL Entry",
        ["account", "cost_center", "project", "debit", "credit", "posting_date"],
        [["company", "=", company], ["is_cancelled", "=", 0], ["account", "in", accounts],
         ["posting_date", "between", [start.isoformat(), end.isoformat()]]],
    )  # fmt: skip
    actuals = []
    for b in budgets:
        first, last = ([*b.fiscal_year.split("-"), b.fiscal_year])[:2]
        lo, hi = years.get(first, (None, None))[0], years.get(last, (None, None))[1]
        field = "cost_center" if b.against == "cost_centre" else "project"
        total = sum(
            (money(e["debit"]) - money(e["credit"]) for e in entries
             if e["account"] == b.account_id and e.get(field) == b.target_id
             and lo and hi and lo <= _date(e["posting_date"]) <= hi),  # type: ignore[operator]
            Decimal(0),
        )  # fmt: skip
        actuals.append(
            BudgetActual(against=b.against, target_id=b.target_id, account_id=b.account_id,
                         fiscal_year=b.fiscal_year, amount=total)
        )  # fmt: skip
    return budgets, actuals


async def _docs(api: Api, doctype: str, company: str, since: date, date_field: str,
                extra: list[list[Any]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    rows = await api.rows(
        doctype,
        ["name"],
        [["company", "=", company], ["docstatus", "<", 2], [date_field, ">=", since.isoformat()],
         *(extra or [])],
    )  # fmt: skip
    return await api.get_many(doctype, [r["name"] for r in rows])


def _requests(docs: list[dict[str, Any]]) -> list[PurchaseRequest]:
    return [
        PurchaseRequest(
            id=d["name"],
            title=_text(d.get("title"), 4000),
            date=_date(d["transaction_date"]),
            status=d.get("status") or DOC_STATUS[d["docstatus"]],
            doc_status=DOC_STATUS[d["docstatus"]],
            lines=[
                RequestLine(
                    id=i["name"],
                    item_code=i["item_code"],
                    qty=qty(i["qty"]),
                    rate=Decimal(str(i["rate"])) if i.get("rate") else None,
                    needed_by=_date(i.get("schedule_date")),
                    ordered_qty=qty(i.get("ordered_qty")),
                    **_coding(i),
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]


def _quotations(docs: list[dict[str, Any]]) -> list[SupplierQuotation]:
    return [
        SupplierQuotation(
            id=d["name"],
            vendor_id=d["supplier"],
            date=_date(d["transaction_date"]),
            valid_till=_date(d.get("valid_till")),
            status=d.get("status") or "Draft",
            doc_status=DOC_STATUS[d["docstatus"]],
            terms=_text(d.get("terms")),
            total=money(d.get("grand_total")),
            lines=[
                QuotationLine(
                    item_code=i["item_code"],
                    qty=qty(i["qty"]),
                    rate=Decimal(str(i["rate"])),
                    lead_time_days=int(i["lead_time_days"])
                    if i.get("lead_time_days") is not None
                    else None,
                    request_id=i.get("material_request") or None,
                    request_line_id=i.get("material_request_item") or None,
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]


def _orders(docs: list[dict[str, Any]]) -> list[PurchaseOrder]:
    return [
        PurchaseOrder(
            id=d["name"],
            vendor_id=d["supplier"],
            date=_date(d["transaction_date"]),
            status=d.get("status") or "Draft",
            doc_status=DOC_STATUS[d["docstatus"]],
            total=money(d.get("grand_total")),
            lines=[
                OrderLine(
                    id=i["name"],
                    item_code=i["item_code"],
                    qty=qty(i["qty"]),
                    rate=Decimal(str(i["rate"])),
                    amount=money(i.get("amount")),
                    received_qty=qty(i.get("received_qty")),
                    billed_amount=money(i.get("billed_amt")),
                    needed_by=_date(i.get("schedule_date")),
                    request_id=i.get("material_request") or None,
                    request_line_id=i.get("material_request_item") or None,
                    **_coding(i),
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]


def _receipts(docs: list[dict[str, Any]]) -> list[PurchaseReceipt]:
    return [
        PurchaseReceipt(
            id=d["name"],
            vendor_id=d["supplier"],
            date=_date(d["posting_date"]),
            status=d.get("status") or "Draft",
            doc_status=DOC_STATUS[d["docstatus"]],
            lines=[
                ReceiptLine(
                    id=i["name"],
                    item_code=i["item_code"],
                    qty=qty(i["qty"]),
                    rejected_qty=qty(i.get("rejected_qty")),
                    rate=Decimal(str(i["rate"])),
                    order_id=i.get("purchase_order") or None,
                    order_line_id=i.get("purchase_order_item") or None,
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]


def _bills(docs: list[dict[str, Any]]) -> list[Bill]:
    return [
        Bill(
            id=d["name"],
            vendor_id=d["supplier"],
            bill_number=d.get("bill_no") or None,
            bill_date=_date(d.get("bill_date")),
            posting_date=_date(d["posting_date"]),
            due_date=_date(d.get("due_date")),
            status=d.get("status") or "Draft",
            doc_status=DOC_STATUS[d["docstatus"]],
            total=money(d.get("grand_total")),
            outstanding=money(d.get("outstanding_amount")),
            lines=[
                BillLine(
                    item_code=i["item_code"],
                    qty=qty(i["qty"]),
                    rate=Decimal(str(i["rate"])),
                    amount=money(i.get("amount")),
                    order_id=i.get("purchase_order") or None,
                    order_line_id=i.get("po_detail") or None,
                    receipt_id=i.get("purchase_receipt") or None,
                    receipt_line_id=i.get("pr_detail") or None,
                    **_coding(i),
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]


def _drop_outside_links(docs: dict[str, list[dict[str, Any]]]) -> None:
    """Links to documents this snapshot doesn't hold (older than the window) are removed."""
    names = {dt: {d["name"] for d in rows} for dt, rows in docs.items()}
    lines = {
        dt: {i["name"] for d in rows for i in d.get("items", []) if i.get("name")}
        for dt, rows in docs.items()
    }
    links = (  # (doctype, document link field, line link field, target doctype)
        ("Supplier Quotation", "material_request", "material_request_item", "Material Request"),
        ("Purchase Order", "material_request", "material_request_item", "Material Request"),
        ("Purchase Receipt", "purchase_order", "purchase_order_item", "Purchase Order"),
        ("Purchase Invoice", "purchase_order", "po_detail", "Purchase Order"),
        ("Purchase Invoice", "purchase_receipt", "pr_detail", "Purchase Receipt"),
    )
    for dt, doc_field, line_field, target in links:
        for d in docs.get(dt, []):
            for i in d.get("items", []):
                if i.get(doc_field) and i[doc_field] not in names[target]:
                    i[doc_field] = None
                if i.get(line_field) and i[line_field] not in lines[target]:
                    i[line_field] = None


async def from_erpnext(
    api: Api, *, company: str, entity_code: str, as_of: date, demo: bool
) -> SnapshotDocument:
    """A read-only snapshot of one ERPNext company (raises SnapshotInvalidError when the
    data doesn't hold together, with the first problems named)."""
    info = await api.get("Company", company)
    buying = await api.get("Buying Settings", "Buying Settings")
    accounts = await api.rows(
        "Account",
        ["name", "account_name", "account_number", "root_type", "account_type"],
        [["company", "=", company], ["is_group", "=", 0]],
    )
    since = as_of - timedelta(days=READ_DAYS)
    docs = {
        "Material Request": await _docs(api, "Material Request", company, since,
                                        "transaction_date",
                                        [["material_request_type", "=", "Purchase"]]),
        "Supplier Quotation": await _docs(api, "Supplier Quotation", company, since,
                                          "transaction_date"),
        "Purchase Order": await _docs(api, "Purchase Order", company, since, "transaction_date"),
        "Purchase Receipt": await _docs(api, "Purchase Receipt", company, since, "posting_date"),
        "Purchase Invoice": await _docs(api, "Purchase Invoice", company, since, "posting_date"),
    }  # fmt: skip
    _drop_outside_links(docs)
    budgets, actuals = await _budgets(api, company)
    host = urlsplit(api.creds.base_url).hostname or "erpnext"
    try:
        doc = SnapshotDocument(
            provenance=Provenance.SYNTHETIC_DEMO if demo else Provenance.ERP_READONLY_EXPORT,
            company_id=f"{host}:{company}"[:100],
            company_name=company,
            entity=entity_code,
            currency=info.get("default_currency") or "USD",
            basis=Basis.ACCRUAL,
            as_of=as_of,
            source_reference=f"ERPNext {api.creds.base_url} company {company!r}, "
            f"documents since {since.isoformat()}",
            accounts=[
                Account(
                    id=a["name"],
                    name=a.get("account_name") or a["name"],
                    number=a.get("account_number") or None,
                    classification=_classification(a),
                )
                for a in accounts
            ],
            vendors=await _vendors(api),
            items=await _items(api, company),
            item_prices=await _prices(api, buying.get("buying_price_list")),
            vendor_contracts=[
                VendorContract(
                    id=c["name"],
                    vendor_id=c["party_name"],
                    start_date=_date(c.get("start_date")),
                    end_date=_date(c.get("end_date")),
                    terms=_text(c.get("contract_terms")),
                    status=c.get("status") or "",
                )
                for c in await api.rows(
                    "Contract",
                    ["name", "party_name", "start_date", "end_date", "contract_terms", "status"],
                    [["party_type", "=", "Supplier"], ["docstatus", "<", 2]],
                )
            ],
            cost_centres=[
                CostCentre(id=c["name"], name=c.get("cost_center_name") or c["name"])
                for c in await api.rows(
                    "Cost Center",
                    ["name", "cost_center_name"],
                    [["company", "=", company], ["is_group", "=", 0]],
                )
            ],
            labs=await _labs(api),
            grants=[
                _grant(p) for p in await api.rows("Project", ["*"], [["company", "=", company]])
            ],
            budgets=budgets,
            budget_actuals=actuals,
            purchase_requests=_requests(docs["Material Request"]),
            supplier_quotations=_quotations(docs["Supplier Quotation"]),
            purchase_orders=_orders(docs["Purchase Order"]),
            purchase_receipts=_receipts(docs["Purchase Receipt"]),
            bills=_bills(docs["Purchase Invoice"]),
        )
    except ValidationError as exc:
        raise SnapshotInvalidError(
            f"ERPNext data didn't fit the contract: {validation_message(exc)}"
        ) from exc
    check_row_limits(doc)
    return doc
