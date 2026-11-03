"""ERPNext -> SnapshotDocument: the Procure-to-Pay and Order-to-Cash collections, read live
over the REST API.

Nothing is written. Masters come whole; purchase documents (requests, quotations, orders,
receipts, supplier invoices) from the last READ_DAYS, cancelled ones left out. A link to a
document outside that window (e.g. a receipt for an old order) is dropped rather than broken:
the snapshot only cites what it contains.

ERPNext's lab is the "Lab" accounting dimension (field `lab`), a grant is a Project (with
the custom grant fields when the site has them), a department is a cost centre.

Order-to-Cash: a client is a Customer (credit limit, payment terms, frozen = on hold, and the
custom "deposit only" / "key account" flags when the site has them); GIA's lab system isn't
connected, so a lab submission is a Sales Order (its custom "report issued on" date and "fee
estimate" when present). Sales invoices, customer payments, selling prices, pricing rules and
sales tax templates come as they are.
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
    Allocation,
    Basis,
    Bill,
    BillLine,
    Budget,
    BudgetActual,
    Client,
    ClientPayment,
    CostCentre,
    Grant,
    Item,
    ItemPrice,
    JournalEntry,
    Lab,
    LedgerBalance,
    LedgerEntry,
    OrderLine,
    PriceRule,
    Provenance,
    PurchaseOrder,
    PurchaseReceipt,
    PurchaseRequest,
    QuotationLine,
    ReceiptLine,
    RequestLine,
    SalesInvoice,
    SalesInvoiceLine,
    SellingPrice,
    SnapshotDocument,
    Submission,
    SubmissionLine,
    SupplierQuotation,
    TaxRule,
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
    rows = await api.rows(
        "Item",
        ["item_code", "item_name", "item_group", "is_stock_item", "is_purchase_item",
         "is_sales_item"],
    )  # fmt: skip
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
            # A site that doesn't say: bought, not sold (the Procure-to-Pay default)
            purchasable=r.get("is_purchase_item") is None or bool(r["is_purchase_item"]),
            sellable=bool(r.get("is_sales_item")),
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
            return_against=(d.get("return_against") or None) if d.get("is_return") else None,
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


# --- Order-to-Cash ---------------------------------------------------------------------------


async def _clients(api: Api, company: str) -> list[Client]:
    rows = await api.rows("Customer", ["*"])
    limits = {
        r["name"]: r.get("credit_limit")
        for r in await api.rows(
            "Customer",
            ["name", "`tabCustomer Credit Limit`.credit_limit"],
            [["Customer Credit Limit", "company", "=", company]],
        )
    }
    days = {
        r["name"]: r.get("credit_days")
        for r in await api.rows(
            "Payment Terms Template", ["name", "`tabPayment Terms Template Detail`.credit_days"]
        )
    }
    contacts = await api.rows(
        "Contact",
        ["email_id", "is_primary_contact", "`tabDynamic Link`.link_name"],
        [["Dynamic Link", "link_doctype", "=", "Customer"]],
        order_by="is_primary_contact desc",
    )
    email: dict[str, str] = {}
    for c in contacts:
        address = _email(c.get("email_id"))
        if address and c.get("link_name") and c["link_name"] not in email:
            email[c["link_name"]] = address
    out = []
    for r in rows:
        terms = r.get("payment_terms") or None
        limit = limits.get(r["name"])
        out.append(
            Client(
                id=r["name"], name=r.get("customer_name") or r["name"],
                group=r.get("customer_group") or None, email=email.get(r["name"]),
                tax_id=r.get("tax_id") or None, territory=r.get("territory") or None,
                tax_category=r.get("tax_category") or None,
                currency=r.get("default_currency") or None,
                credit_limit=money(limit) if limit else None, payment_terms=terms,
                terms_days=int(str(days[terms])) if terms and days.get(terms) is not None
                else None,
                deposit_only=bool(r.get("deposit_only")), key_account=bool(r.get("key_account")),
                status="Disabled" if r.get("disabled") else "On hold" if r.get("is_frozen")
                else "Active",
                since=_date(r.get("creation")),
            )
        )  # fmt: skip
    return out


def _submissions(docs: list[dict[str, Any]]) -> list[Submission]:
    return [
        Submission(
            id=d["name"], client_id=d["customer"], date=_date(d["transaction_date"]),
            status=d.get("status") or DOC_STATUS[d["docstatus"]],
            doc_status=DOC_STATUS[d["docstatus"]], total=money(d.get("grand_total")),
            fee_estimate=money(d["fee_estimate"]) if d.get("fee_estimate") else None,
            report_issued_on=_date(d.get("report_issued_on")),
            lines=[
                SubmissionLine(
                    id=i["name"], item_code=i["item_code"], qty=qty(i["qty"]),
                    rate=Decimal(str(i["rate"])), amount=money(i.get("amount")),
                    added=bool(i.get("added_service")), billed_amount=money(i.get("billed_amt")),
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]  # fmt: skip


def _sales_invoices(docs: list[dict[str, Any]], currency: str) -> list[SalesInvoice]:
    return [
        SalesInvoice(
            id=d["name"], client_id=d["customer"], posting_date=_date(d["posting_date"]),
            due_date=_date(d.get("due_date")), status=d.get("status") or "Draft",
            doc_status=DOC_STATUS[d["docstatus"]], currency=d.get("currency") or currency,
            net_total=money(d.get("net_total")),
            tax_total=money(d.get("total_taxes_and_charges")),
            total=money(d.get("grand_total")), outstanding=money(d.get("outstanding_amount")),
            return_against=(d.get("return_against") or None) if d.get("is_return") else None,
            reference=d.get("finance_acc_ref") or None,
            lines=[
                SalesInvoiceLine(
                    item_code=i["item_code"], qty=qty(i["qty"]), rate=Decimal(str(i["rate"])),
                    amount=money(i.get("amount")), submission_id=i.get("sales_order") or None,
                    submission_line_id=i.get("so_detail") or None,
                )
                for i in d.get("items", [])
            ],
        )
        for d in docs
    ]  # fmt: skip


def _client_payments(docs: list[dict[str, Any]], invoices: set[str]) -> list[ClientPayment]:
    """Receipts from clients; an allocation to an invoice outside the window is left out."""
    return [
        ClientPayment(
            id=d["name"], client_id=d["party"], date=_date(d["posting_date"]),
            amount=money(d.get("received_amount") or d.get("paid_amount")),
            reference=d.get("reference_no") or None,
            allocations=[
                Allocation(invoice_id=r["reference_name"], amount=money(r["allocated_amount"]))
                for r in d.get("references", [])
                if r.get("reference_doctype") == "Sales Invoice"
                and r.get("reference_name") in invoices and money(r.get("allocated_amount")) > 0
            ],
        )
        for d in docs
        if d.get("party") and money(d.get("received_amount") or d.get("paid_amount")) > 0
    ]  # fmt: skip


async def _selling_prices(api: Api, price_list: str | None) -> list[SellingPrice]:
    filters: list[list[Any]] = [["selling", "=", 1]]
    if price_list:
        filters.append(["price_list", "=", price_list])
    rows = await api.rows(
        "Item Price", ["item_code", "customer", "price_list_rate", "currency"], filters
    )
    seen: set[tuple[str, str | None]] = set()
    out = []
    for r in rows:
        key = (r["item_code"], r.get("customer") or None)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SellingPrice(item_code=r["item_code"], client_id=r.get("customer") or None,
                         rate=Decimal(str(r["price_list_rate"])),
                         currency=r.get("currency") or "USD")
        )  # fmt: skip
    return out


async def _price_rules(api: Api, company: str) -> list[PriceRule]:
    names = [
        r["name"]
        for r in await api.rows(
            "Pricing Rule", ["name"], [["selling", "=", 1], ["disable", "=", 0]]
        )
    ]
    out = []
    for d in await api.get_many("Pricing Rule", names):
        if d.get("company") not in (None, "", company):
            continue
        targets: list[tuple[str | None, str | None]] = (
            [(i.get("item_code"), None) for i in d.get("items", [])]
            if d.get("apply_on") == "Item Code"
            else [(None, g.get("item_group")) for g in d.get("item_groups", [])]
            if d.get("apply_on") == "Item Group"
            else []
        )
        discount = d.get("rate_or_discount") == "Discount Percentage"
        for n, (code, group) in enumerate(targets):
            out.append(
                PriceRule(
                    id=f"{d['name']}#{n + 1}" if len(targets) > 1 else d["name"],
                    item_code=code, item_group=group,
                    client_id=d.get("customer") if d.get("applicable_for") == "Customer" else None,
                    client_group=d.get("customer_group")
                    if d.get("applicable_for") == "Customer Group" else None,
                    discount_pct=Decimal(str(d.get("discount_percentage") or 0))
                    if discount else None,
                    rate=Decimal(str(d["rate"])) if not discount and d.get("rate") else None,
                    valid_from=_date(d.get("valid_from")), valid_upto=_date(d.get("valid_upto")),
                )
            )  # fmt: skip
    return out


async def _tax_rules(api: Api, company: str) -> list[TaxRule]:
    names = [
        r["name"]
        for r in await api.rows(
            "Sales Taxes and Charges Template", ["name"],
            [["company", "=", company], ["disabled", "=", 0]],
        )
    ]  # fmt: skip
    out = []
    for d in await api.get_many("Sales Taxes and Charges Template", names):
        rows = [t for t in d.get("taxes", []) if t.get("charge_type") == "On Net Total"]
        out.append(
            TaxRule(
                id=d["name"], tax_category=d.get("tax_category") or None,
                rate_pct=sum((Decimal(str(t.get("rate") or 0)) for t in rows), Decimal(0)),
                account_id=rows[0].get("account_head") if rows else None,
                default=bool(d.get("is_default")),
            )
        )  # fmt: skip
    return out


def _ledger_kind(account: dict[str, Any]) -> str | None:
    if account.get("account_type") == "Payable" and account.get("root_type") == "Liability":
        return "payable"
    if account.get("account_type") == "Stock Received But Not Billed":
        return "received_not_billed"
    if str(account.get("account_name", "")).lower().startswith("accrued"):
        return "accrued"
    return None


async def _ledgers(
    api: Api, company: str, accounts: list[dict[str, Any]], as_of: date, since: date
) -> tuple[list[LedgerBalance], list[LedgerEntry], list[JournalEntry]]:
    """The AP control accounts (payable, received-not-billed, accrued): their balances at
    as_of, their postings since `since`, and the journal entries of the window."""
    kinds = {a["name"]: k for a in accounts if (k := _ledger_kind(a))}
    entries = (
        await api.rows(
            "GL Entry",
            ["name", "account", "posting_date", "debit", "credit", "voucher_type", "voucher_no",
             "party"],
            [["company", "=", company], ["is_cancelled", "=", 0],
             ["account", "in", sorted(kinds)], ["posting_date", "<=", as_of.isoformat()]],
        )
        if kinds
        else []
    )  # fmt: skip
    balances = {name: Decimal(0) for name in kinds}
    window: list[LedgerEntry] = []
    for e in entries:
        amount = money(e.get("credit")) - money(e.get("debit"))
        balances[e["account"]] += amount
        posted = _date(e["posting_date"])
        if posted and posted >= since:
            window.append(
                LedgerEntry(id=e["name"], account_id=e["account"], kind=kinds[e["account"]],
                            posting_date=posted, amount=amount,
                            voucher_type=e.get("voucher_type") or "",
                            voucher_id=e.get("voucher_no") or "", party=e.get("party") or None)
            )  # fmt: skip
    journals = await api.rows(
        "Journal Entry",
        ["name", "posting_date", "docstatus", "total_debit", "user_remark", "finance_acc_ref"],
        [["company", "=", company], ["docstatus", "<", 2],
         ["posting_date", ">=", since.isoformat()]],
    )  # fmt: skip
    return (
        [LedgerBalance(account_id=n, kind=kinds[n], as_of=as_of, balance=b)
         for n, b in balances.items()],
        window,
        [JournalEntry(id=j["name"], posting_date=_date(j["posting_date"]),
                      doc_status=DOC_STATUS[j["docstatus"]], total=money(j.get("total_debit")),
                      remark=_text(j.get("user_remark")),
                      reference=j.get("finance_acc_ref") or None)
         for j in journals],
    )  # fmt: skip


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
        ("Sales Invoice", "sales_order", "so_detail", "Sales Order"),
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
    selling = await api.get("Selling Settings", "Selling Settings")
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
        "Sales Order": await _docs(api, "Sales Order", company, since, "transaction_date"),
        "Sales Invoice": await _docs(api, "Sales Invoice", company, since, "posting_date"),
        "Payment Entry": await _docs(api, "Payment Entry", company, since, "posting_date",
                                     [["party_type", "=", "Customer"],
                                      ["payment_type", "=", "Receive"], ["docstatus", "=", 1]]),
    }  # fmt: skip
    _drop_outside_links(docs)
    budgets, actuals = await _budgets(api, company)
    ledger_balances, ledger_entries, journal_entries = await _ledgers(
        api, company, accounts, as_of, since
    )
    host = urlsplit(api.creds.base_url).hostname or "erpnext"
    currency = info.get("default_currency") or "USD"
    sales_invoices = _sales_invoices(docs["Sales Invoice"], currency)
    try:
        doc = SnapshotDocument(
            provenance=Provenance.SYNTHETIC_DEMO if demo else Provenance.ERP_READONLY_EXPORT,
            company_id=f"{host}:{company}"[:100],
            company_name=company,
            entity=entity_code,
            currency=currency,
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
            ledger_balances=ledger_balances,
            ledger_entries=ledger_entries,
            journal_entries=journal_entries,
            clients=await _clients(api, company),
            submissions=_submissions(docs["Sales Order"]),
            sales_invoices=sales_invoices,
            client_payments=_client_payments(docs["Payment Entry"], {i.id for i in sales_invoices}),
            selling_prices=await _selling_prices(api, selling.get("selling_price_list")),
            price_rules=await _price_rules(api, company),
            tax_rules=await _tax_rules(api, company),
        )
    except ValidationError as exc:
        raise SnapshotInvalidError(
            f"ERPNext data didn't fit the contract: {validation_message(exc)}"
        ) from exc
    check_row_limits(doc)
    return doc
