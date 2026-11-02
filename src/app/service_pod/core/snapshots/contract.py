"""The normalized source contract: what a read-only QuickBooks export must look like.

Every collection is optional. Leaving one out (None) means "the source doesn't supply it"
and is recorded in the snapshot's coverage; an empty list means "supplied, nothing there".
Workflows refuse snapshots that lack a collection they need instead of inventing data.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Money = Annotated[Decimal, Field(max_digits=18, decimal_places=2, allow_inf_nan=False)]
Period = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]  # e.g. 2026-09
Id = Annotated[str, Field(min_length=1, max_length=100)]
Text = Annotated[str, Field(max_length=4000)]
Name = Annotated[str, Field(min_length=1, max_length=200)]


class Collection(StrEnum):
    CUSTOMERS = "customers"
    INVOICES = "invoices"
    PAYMENTS = "payments"
    ACCOUNTS = "accounts"
    GL_LINES = "gl_lines"
    TRANSACTIONS = "transactions"
    BANK_RECEIPTS = "bank_receipts"
    CONTRACTS = "contracts"
    PLANNED_OUTFLOWS = "planned_outflows"
    CASH_POSITION = "cash_position"
    BALANCE_SHEETS = "balance_sheets"
    CLOSE_STATUS = "close_status"
    # Procure-to-Pay (Finance POD): read from an ERP such as ERPNext
    VENDORS = "vendors"
    ITEMS = "items"
    ITEM_PRICES = "item_prices"
    VENDOR_CONTRACTS = "vendor_contracts"
    COST_CENTRES = "cost_centres"
    LABS = "labs"
    GRANTS = "grants"
    BUDGETS = "budgets"
    BUDGET_ACTUALS = "budget_actuals"
    PURCHASE_REQUESTS = "purchase_requests"
    SUPPLIER_QUOTATIONS = "supplier_quotations"
    PURCHASE_ORDERS = "purchase_orders"
    PURCHASE_RECEIPTS = "purchase_receipts"
    BILLS = "bills"


# Added for the Finance POD: left out of a snapshot's stored payload when absent, so the
# Service POD's existing exports keep their digests
AP_COLLECTIONS = frozenset(
    {
        Collection.VENDORS, Collection.ITEMS, Collection.ITEM_PRICES,
        Collection.VENDOR_CONTRACTS, Collection.COST_CENTRES, Collection.LABS,
        Collection.GRANTS, Collection.BUDGETS, Collection.BUDGET_ACTUALS,
        Collection.PURCHASE_REQUESTS, Collection.SUPPLIER_QUOTATIONS,
        Collection.PURCHASE_ORDERS, Collection.PURCHASE_RECEIPTS, Collection.BILLS,
    }
)  # fmt: skip


class Basis(StrEnum):
    ACCRUAL = "Accrual"
    CASH = "Cash"


class Provenance(StrEnum):
    QUICKBOOKS_READONLY_EXPORT = "QUICKBOOKS_READONLY_EXPORT"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"  # fictional data, always labelled as demo
    ERP_READONLY_EXPORT = "ERP_READONLY_EXPORT"  # read from an ERP (e.g. ERPNext) over its API


class AccountClass(StrEnum):
    INCOME = "Income"
    COST_OF_GOODS_SOLD = "CostOfGoodsSold"
    EXPENSE = "Expense"
    OTHER_INCOME = "OtherIncome"
    OTHER_EXPENSE = "OtherExpense"
    ASSET = "Asset"
    LIABILITY = "Liability"
    EQUITY = "Equity"


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class Customer(_Row):
    id: Id
    name: Name
    email: EmailStr | None = None  # the verified contact collections mail goes to
    contact_name: Name | None = None


class Invoice(_Row):
    id: Id
    number: Id
    customer_id: Id
    txn_date: date
    due_date: date
    original_amount: Money
    balance: Money  # still open
    terms: Name | None = None
    document_ref: Text | None = None

    @model_validator(mode="after")
    def _balance_within_amount(self) -> Self:
        if self.balance < 0 or self.balance > self.original_amount:
            raise ValueError(f"invoice {self.number}: balance must be between 0 and the amount")
        return self


class Allocation(_Row):
    invoice_id: Id
    amount: Annotated[Money, Field(gt=0)]


class Payment(_Row):
    id: Id
    customer_id: Id
    date: date
    amount: Annotated[Money, Field(gt=0)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    reference: Id  # bank / wire reference
    allocations: list[Allocation] = []


class Account(_Row):
    id: Id
    name: Name
    number: Annotated[str, Field(max_length=50)] | None = None
    classification: AccountClass


class GlLine(_Row):
    """One account's movement in one period, as the P&L / GL report states it."""

    id: Id
    account_id: Id
    period: Period
    amount: Money
    report_id: Id
    transaction_ids: list[Id] = []
    business_unit: Name | None = None  # QuickBooks class / department, when the export has one


class Transaction(_Row):
    id: Id
    date: date
    period: Period
    type: Name  # Invoice, Bill, JournalEntry, CreditMemo...
    counterparty: Name | None = None
    account_id: Id
    amount: Money  # signed, net of tax
    tax: Money = Decimal(0)
    status: Literal["Posted", "Draft", "Voided"]
    gl_line_id: Id | None = None
    document_ref: Text | None = None
    entity: Name | None = None
    business_unit: Name | None = None


class BankReceipt(_Row):
    reference: Id
    payer: Name
    date: date
    amount: Annotated[Money, Field(gt=0)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    cleared: bool
    proof_reference: Text | None = None


class Contract(_Row):
    id: Id
    customer_id: Id
    invoice_ids: list[Id] = []
    terms: Text | None = None
    status: Name


class PlannedOutflow(_Row):
    id: Id
    date: date
    amount: Annotated[Money, Field(gt=0)]
    category: Name
    approved: bool
    approval_ref: Id | None = None


class CashPosition(_Row):
    as_of: date
    bank_balance: Money
    quickbooks_cash_balance: Money
    reconciliation_balance: Money | None = None  # never defaulted from the cash balance
    policy_buffer: Annotated[Money, Field(ge=0)]
    cleared: bool
    proof_reference: Text | None = None


class BalanceSheet(_Row):
    period: Period
    assets: Money
    liabilities: Money
    equity: Money
    report_id: Id


class CloseStatus(_Row):
    period: Period
    status: Literal["Open", "Closed"]
    required_checks: list[Name] = []


# --- Procure-to-Pay ----------------------------------------------------------------------
# Codes are the ERP's own ids. Coding on a line: cost centre (department), lab and grant
# (ERPNext: cost centre, the "Lab" accounting dimension and the project).

DocStatus = Literal["Draft", "Submitted", "Cancelled"]
Day = date  # for fields declared after a field named `date`
Qty = Annotated[Decimal, Field(max_digits=18, decimal_places=6, ge=0, allow_inf_nan=False)]
Rate = Annotated[Decimal, Field(max_digits=18, decimal_places=6, allow_inf_nan=False)]


class Coding(_Row):
    cost_centre_id: Id | None = None
    lab_id: Id | None = None
    grant_id: Id | None = None
    account_id: Id | None = None


class Vendor(_Row):
    id: Id
    name: Name
    group: Name | None = None
    email: EmailStr | None = None  # the verified contact (vendor mail goes only here)
    tax_id: Annotated[str, Field(max_length=50)] | None = None
    status: Literal["Active", "Disabled", "On hold"]
    # A digest of the bank details on file (never the numbers): a change shows as a new digest
    bank_fingerprint: Annotated[str, Field(max_length=64)] | None = None


class Item(_Row):
    code: Id
    name: Name
    group: Name
    stock_item: bool
    standard_rate: Rate | None = None
    expense_account_id: Id | None = None


class ItemPrice(_Row):
    """A buying price: the price list's standard rate (vendor_id None) or a vendor's
    contract price."""

    item_code: Id
    vendor_id: Id | None = None
    rate: Rate
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class VendorContract(_Row):
    id: Id
    vendor_id: Id
    start_date: date | None = None
    end_date: date | None = None
    terms: Text | None = None
    status: Name


class CostCentre(_Row):
    id: Id
    name: Name


class Lab(_Row):
    id: Id
    name: Name


class Grant(_Row):
    id: Id
    name: Name
    funder: Name | None = None
    start_date: date | None = None
    end_date: date | None = None
    restricted: bool = False
    allowed_item_groups: list[Name] = []  # empty: any (when restricted, ask)
    status: Name


class Budget(_Row):
    id: Id
    against: Literal["cost_centre", "grant"]
    target_id: Id
    account_id: Id
    fiscal_year: Name
    amount: Money


class BudgetActual(_Row):
    """Posted expense on a budget's target and account in the fiscal year (from the GL)."""

    against: Literal["cost_centre", "grant"]
    target_id: Id
    account_id: Id
    fiscal_year: Name
    amount: Money


class RequestLine(Coding):
    id: Id
    item_code: Id
    qty: Qty
    rate: Rate | None = None
    needed_by: date | None = None
    ordered_qty: Qty = Decimal(0)


class PurchaseRequest(_Row):
    id: Id
    title: Text | None = None
    date: date
    status: Name  # the ERP's own: Draft, Pending, Ordered, Received...
    doc_status: DocStatus
    lines: list[RequestLine]


class QuotationLine(_Row):
    item_code: Id
    qty: Qty
    rate: Rate
    lead_time_days: Annotated[int, Field(ge=0)] | None = None
    request_id: Id | None = None
    request_line_id: Id | None = None


class SupplierQuotation(_Row):
    id: Id
    vendor_id: Id
    date: date
    valid_till: Day | None = None
    status: Name
    doc_status: DocStatus
    terms: Text | None = None
    total: Money
    lines: list[QuotationLine]


class OrderLine(Coding):
    id: Id
    item_code: Id
    qty: Qty
    rate: Rate
    amount: Money
    received_qty: Qty = Decimal(0)
    billed_amount: Money = Decimal(0)
    needed_by: date | None = None
    request_id: Id | None = None
    request_line_id: Id | None = None


class PurchaseOrder(_Row):
    id: Id
    vendor_id: Id
    date: date
    status: Name
    doc_status: DocStatus
    total: Money
    lines: list[OrderLine]


class ReceiptLine(_Row):
    id: Id
    item_code: Id
    qty: Qty  # accepted
    rejected_qty: Qty = Decimal(0)
    rate: Rate
    order_id: Id | None = None
    order_line_id: Id | None = None


class PurchaseReceipt(_Row):
    id: Id
    vendor_id: Id
    date: date
    status: Name
    doc_status: DocStatus
    lines: list[ReceiptLine]


class BillLine(Coding):
    item_code: Id
    qty: Qty
    rate: Rate
    amount: Money
    order_id: Id | None = None
    order_line_id: Id | None = None
    receipt_id: Id | None = None
    receipt_line_id: Id | None = None


class Bill(_Row):
    """A supplier invoice. Draft: arrived and waiting (to be matched); Submitted: posted."""

    id: Id
    vendor_id: Id
    bill_number: Id | None = None
    bill_date: date | None = None
    posting_date: date
    due_date: date | None = None
    status: Name
    doc_status: DocStatus
    total: Money
    outstanding: Money
    lines: list[BillLine]


def _unique(rows: Sequence[_Row] | None, key: str, what: str) -> set[str]:
    seen: set[str] = set()
    for row in rows or []:
        value = getattr(row, key)
        if value in seen:
            raise ValueError(f"{what}: duplicate {key} {value!r}")
        seen.add(value)
    return seen


class SnapshotDocument(BaseModel):
    """A whole normalized export of one company / entity."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provenance: Provenance
    company_id: Id
    company_name: Name
    entity: Name  # must equal the code of the legal entity it is imported into
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    basis: Basis
    as_of: date
    source_reference: Text  # which extraction produced it (file, report run, export id)

    customers: list[Customer] | None = None
    invoices: list[Invoice] | None = None
    payments: list[Payment] | None = None
    accounts: list[Account] | None = None
    gl_lines: list[GlLine] | None = None
    transactions: list[Transaction] | None = None
    bank_receipts: list[BankReceipt] | None = None
    contracts: list[Contract] | None = None
    planned_outflows: list[PlannedOutflow] | None = None
    cash_position: CashPosition | None = None
    balance_sheets: list[BalanceSheet] | None = None
    close_status: list[CloseStatus] | None = None
    vendors: list[Vendor] | None = None
    items: list[Item] | None = None
    item_prices: list[ItemPrice] | None = None
    vendor_contracts: list[VendorContract] | None = None
    cost_centres: list[CostCentre] | None = None
    labs: list[Lab] | None = None
    grants: list[Grant] | None = None
    budgets: list[Budget] | None = None
    budget_actuals: list[BudgetActual] | None = None
    purchase_requests: list[PurchaseRequest] | None = None
    supplier_quotations: list[SupplierQuotation] | None = None
    purchase_orders: list[PurchaseOrder] | None = None
    purchase_receipts: list[PurchaseReceipt] | None = None
    bills: list[Bill] | None = None

    @property
    def coverage(self) -> list[Collection]:
        return [c for c in Collection if getattr(self, c.value) is not None]

    def row_count(self, collection: Collection) -> int:
        value = getattr(self, collection.value)
        if value is None:
            return 0
        return len(value) if isinstance(value, list) else 1

    @model_validator(mode="after")
    def _check_links(self) -> Self:
        customers = _unique(self.customers, "id", "customers")
        invoices = _unique(self.invoices, "id", "invoices")
        _unique(self.invoices, "number", "invoices")
        _unique(self.payments, "id", "payments")
        accounts = _unique(self.accounts, "id", "accounts")
        _unique(self.gl_lines, "id", "gl_lines")
        _unique(self.transactions, "id", "transactions")
        _unique(self.bank_receipts, "reference", "bank_receipts")
        _unique(self.balance_sheets, "period", "balance_sheets")
        _unique(self.close_status, "period", "close_status")

        if self.customers is not None:
            for inv in self.invoices or []:
                if inv.customer_id not in customers:
                    raise ValueError(f"invoice {inv.number}: unknown customer {inv.customer_id}")
            for pay in self.payments or []:
                if pay.customer_id not in customers:
                    raise ValueError(f"payment {pay.id}: unknown customer {pay.customer_id}")
        if self.invoices is not None:
            for pay in self.payments or []:
                for alloc in pay.allocations:
                    if alloc.invoice_id not in invoices:
                        raise ValueError(f"payment {pay.id}: unknown invoice {alloc.invoice_id}")
                if sum((a.amount for a in pay.allocations), Decimal(0)) > pay.amount:
                    raise ValueError(f"payment {pay.id}: allocations exceed the payment")

        gl = {g.id: g for g in self.gl_lines or []}
        if self.accounts is not None:
            for entry in gl.values():
                if entry.account_id not in accounts:
                    raise ValueError(f"GL line {entry.id}: unknown account {entry.account_id}")
        txns = {t.id: t for t in self.transactions or []}
        for txn in txns.values():
            if txn.date.strftime("%Y-%m") != txn.period:
                raise ValueError(f"transaction {txn.id}: date is outside period {txn.period}")
            if txn.entity is not None and txn.entity != self.entity:
                raise ValueError(f"transaction {txn.id}: belongs to entity {txn.entity}")
            if txn.gl_line_id is None or self.gl_lines is None:
                continue
            line = gl.get(txn.gl_line_id)
            if line is None:
                raise ValueError(f"transaction {txn.id}: unknown GL line {txn.gl_line_id}")
            if (line.account_id, line.period) != (txn.account_id, txn.period):
                raise ValueError(f"transaction {txn.id}: account/period differ from GL line")
            if txn.id not in line.transaction_ids:
                raise ValueError(f"transaction {txn.id}: GL line {line.id} doesn't cite it")
        for gl_line in gl.values():
            for txn_id in gl_line.transaction_ids:
                cited = txns.get(txn_id)
                if cited is None or cited.gl_line_id != gl_line.id:
                    raise ValueError(f"GL line {gl_line.id}: transaction {txn_id} doesn't cite it")
        self._check_procurement()
        return self

    def _check_procurement(self) -> None:
        """Every reference between the Procure-to-Pay collections points at a row the
        snapshot has (checked when the referenced collection is supplied)."""
        vendors = _unique(self.vendors, "id", "vendors")
        items = _unique(self.items, "code", "items")
        masters = {
            "cost_centre_id": _unique(self.cost_centres, "id", "cost_centres"),
            "lab_id": _unique(self.labs, "id", "labs"),
            "grant_id": _unique(self.grants, "id", "grants"),
            "account_id": {a.id for a in self.accounts or []},
        }
        given = {
            "cost_centre_id": self.cost_centres is not None,
            "lab_id": self.labs is not None,
            "grant_id": self.grants is not None,
            "account_id": self.accounts is not None,
        }
        requests = _unique(self.purchase_requests, "id", "purchase_requests")
        orders = _unique(self.purchase_orders, "id", "purchase_orders")
        receipts = _unique(self.purchase_receipts, "id", "purchase_receipts")
        _unique(self.supplier_quotations, "id", "supplier_quotations")
        _unique(self.bills, "id", "bills")
        _unique(self.budgets, "id", "budgets")

        def vendor(what: str, vendor_id: str) -> None:
            if self.vendors is not None and vendor_id not in vendors:
                raise ValueError(f"{what}: unknown vendor {vendor_id}")

        def item(what: str, code: str) -> None:
            if self.items is not None and code not in items:
                raise ValueError(f"{what}: unknown item {code}")

        def coded(what: str, line: Coding) -> None:
            for field, known in masters.items():
                value = getattr(line, field)
                if value is not None and given[field] and value not in known:
                    raise ValueError(f"{what}: unknown {field.removesuffix('_id')} {value}")

        def linked(what: str, value: str | None, known: set[str], present: bool) -> None:
            if value is not None and present and value not in known:
                raise ValueError(f"{what}: unknown {value}")

        for price in self.item_prices or []:
            item(f"price of {price.item_code}", price.item_code)
            if price.vendor_id is not None:
                vendor(f"price of {price.item_code}", price.vendor_id)
        for contract in self.vendor_contracts or []:
            vendor(f"contract {contract.id}", contract.vendor_id)
        for request in self.purchase_requests or []:
            for rl in request.lines:
                item(f"request {request.id}", rl.item_code)
                coded(f"request {request.id}", rl)
        for quote in self.supplier_quotations or []:
            vendor(f"quotation {quote.id}", quote.vendor_id)
            for ql in quote.lines:
                item(f"quotation {quote.id}", ql.item_code)
                linked(f"quotation {quote.id} request", ql.request_id, requests,
                       self.purchase_requests is not None)  # fmt: skip
        order_lines: set[str] = set()
        for order in self.purchase_orders or []:
            vendor(f"order {order.id}", order.vendor_id)
            for ol in order.lines:
                order_lines.add(ol.id)
                item(f"order {order.id}", ol.item_code)
                coded(f"order {order.id}", ol)
                linked(f"order {order.id} request", ol.request_id, requests,
                       self.purchase_requests is not None)  # fmt: skip
        receipt_lines: set[str] = set()
        for receipt in self.purchase_receipts or []:
            vendor(f"receipt {receipt.id}", receipt.vendor_id)
            for rcl in receipt.lines:
                receipt_lines.add(rcl.id)
                item(f"receipt {receipt.id}", rcl.item_code)
                present = self.purchase_orders is not None
                linked(f"receipt {receipt.id} order", rcl.order_id, orders, present)
                linked(f"receipt {receipt.id} order line", rcl.order_line_id, order_lines, present)
        for bill in self.bills or []:
            vendor(f"bill {bill.id}", bill.vendor_id)
            for bl in bill.lines:
                item(f"bill {bill.id}", bl.item_code)
                coded(f"bill {bill.id}", bl)
                present = self.purchase_orders is not None
                linked(f"bill {bill.id} order", bl.order_id, orders, present)
                linked(f"bill {bill.id} order line", bl.order_line_id, order_lines, present)
                present = self.purchase_receipts is not None
                linked(f"bill {bill.id} receipt", bl.receipt_id, receipts, present)
                linked(f"bill {bill.id} receipt line", bl.receipt_line_id, receipt_lines, present)
        for budget in self.budgets or []:
            known, present = (
                (masters["cost_centre_id"], given["cost_centre_id"])
                if budget.against == "cost_centre"
                else (masters["grant_id"], given["grant_id"])
            )
            linked(f"budget {budget.id}", budget.target_id, known, present)
