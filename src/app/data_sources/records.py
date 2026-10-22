"""Canonical finance records. Every source (QuickBooks sync, file upload) is normalized into
these shapes, so agents read the same data whichever system it came from."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

CENT = Decimal("0.01")

# Amounts are kept to the cent. JSON floats (QuickBooks sends 12500.0) go through str() so
# no binary noise gets in; more than two decimals is an error, never silently rounded
Money = Annotated[
    Decimal,
    BeforeValidator(lambda v: Decimal(str(v)) if isinstance(v, float) else v),
    Field(max_digits=18, decimal_places=2),
    AfterValidator(lambda v: v.quantize(CENT)),
]


def _period(value: object) -> object:
    """A month as YYYY-MM; a full date (2026-09-30) is taken as its month."""
    if isinstance(value, date):
        return f"{value:%Y-%m}"
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:7]
    return value


# A month, e.g. "2026-09" (a close period)
Period = Annotated[str, BeforeValidator(_period), Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


def month_end(period: str) -> date:
    year, month = int(period[:4]), int(period[5:7])
    following = date(year + month // 12, month % 12 + 1, 1)
    return date.fromordinal(following.toordinal() - 1)


class RecordType(StrEnum):
    VENDOR = "vendor"
    BILL = "bill"
    PURCHASE_ORDER = "purchase_order"
    ACCOUNT = "account"
    CUSTOMER = "customer"
    INVOICE = "invoice"
    PAYMENT = "payment"
    EXPENSE = "expense"
    ACCOUNT_BALANCE = "account_balance"
    SUBLEDGER_TOTAL = "subledger_total"
    PERIOD_RESULT = "period_result"


class Record(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    external_id: str = Field(min_length=1, max_length=100)

    # Columns copied to finance_records for lookups; subclasses map them to their own fields
    @property
    def reference(self) -> str:
        raise NotImplementedError

    @property
    def counterparty(self) -> str | None:
        return None

    @property
    def amount(self) -> Decimal | None:
        return None

    @property
    def txn_date(self) -> date | None:
        return None


class Vendor(Record):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    tax_id: str | None = Field(default=None, max_length=50)
    active: bool = True

    @property
    def reference(self) -> str:
        return self.name


class Bill(Record):
    """A supplier invoice."""

    doc_number: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)
    total: Money
    tax_total: Money | None = None
    bill_date: date | None = None
    due_date: date | None = None
    po_number: str | None = Field(default=None, max_length=100)
    account: str | None = Field(default=None, max_length=100)
    balance: Money | None = None  # still to pay; None when the source doesn't say

    @property
    def reference(self) -> str:
        return self.doc_number

    @property
    def counterparty(self) -> str | None:
        return self.vendor_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.bill_date

    @property
    def open_amount(self) -> Decimal:
        """The balance; without one, the whole total (a bill is unpaid unless told otherwise)."""
        return self.balance if self.balance is not None else self.total


class PurchaseOrder(Record):
    po_number: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)
    total: Money
    received_amount: Money | None = None
    status: str | None = Field(default=None, max_length=50)
    po_date: date | None = None

    @property
    def reference(self) -> str:
        return self.po_number

    @property
    def counterparty(self) -> str | None:
        return self.vendor_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.po_date


class Account(Record):
    """A GL account from the chart of accounts."""

    number: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    account_type: str | None = Field(default=None, max_length=100)  # e.g. Bank, Expense
    current_balance: Money | None = None

    @property
    def reference(self) -> str:
        return self.number or self.name


class Customer(Record):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    active: bool = True
    balance: Money | None = None  # total open balance, as the source reports it

    @property
    def reference(self) -> str:
        return self.name


class Invoice(Record):
    """A customer (sales) invoice: the receivable side, unlike Bill."""

    doc_number: str = Field(min_length=1, max_length=100)
    customer_name: str = Field(min_length=1, max_length=200)
    total: Money
    balance: Money | None = None  # still open; None when the source doesn't say
    invoice_date: date | None = None
    due_date: date | None = None
    paid_date: date | None = None  # when it was fully paid (the last payment's date)
    # What was sold, one "item: amount" per line (contracts: the performance obligations)
    line_items: str | None = Field(default=None, max_length=4000)
    # Earliest and latest service date on its lines (when the source has them)
    service_start: date | None = None
    service_end: date | None = None

    @property
    def reference(self) -> str:
        return self.doc_number

    @property
    def counterparty(self) -> str | None:
        return self.customer_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.invoice_date

    @property
    def open_amount(self) -> Decimal:
        """The balance; without one, nothing if it was paid, else the whole total."""
        if self.balance is not None:
            return self.balance
        return Decimal("0.00") if self.paid_date else self.total


class Payment(Record):
    """A payment received from a customer."""

    reference_number: str = Field(min_length=1, max_length=100)  # e.g. the wire or check no.
    customer_name: str = Field(min_length=1, max_length=200)
    total: Money
    payment_date: date | None = None
    invoice_number: str | None = Field(default=None, max_length=100)  # first invoice applied to
    applied_amount: Money | None = None  # how much of it went to that invoice
    unapplied_amount: Money | None = None
    memo: str | None = Field(default=None, max_length=4000)  # remittance advice / note

    @property
    def reference(self) -> str:
        return self.reference_number

    @property
    def counterparty(self) -> str | None:
        return self.customer_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.payment_date


class Expense(Record):
    """Money spent by card, cash or check (QuickBooks: Purchase)."""

    transaction_id: str = Field(min_length=1, max_length=100)
    vendor_name: str = Field(min_length=1, max_length=200)  # the merchant
    total: Money
    expense_date: date | None = None
    payment_type: str | None = Field(default=None, max_length=50)  # CreditCard, Cash, Check
    account: str | None = Field(default=None, max_length=200)  # expense category
    employee: str | None = Field(default=None, max_length=200)
    has_receipt: bool = False

    @property
    def reference(self) -> str:
        return self.transaction_id

    @property
    def counterparty(self) -> str | None:
        return self.vendor_name

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return self.expense_date


class AccountBalance(Record):
    """An account's balance at a month end (from the trial balance), debits positive."""

    account_name: str = Field(min_length=1, max_length=200)
    account_number: str | None = Field(default=None, max_length=50)
    account_type: str | None = Field(default=None, max_length=100)  # e.g. Accounts Receivable
    period: Period
    balance: Money

    @property
    def reference(self) -> str:
        return f"{self.period} {self.account_number or self.account_name}"

    @property
    def amount(self) -> Decimal | None:
        return self.balance

    @property
    def txn_date(self) -> date | None:
        return month_end(self.period)

    def matches(self, account: str) -> bool:
        """Whether `account` names this account (by name or number, ignoring case)."""
        wanted = account.strip().lower()
        return wanted in (self.account_name.lower(), (self.account_number or "").lower())


class SubledgerTotal(Record):
    """A subledger's total at a month end, e.g. the AR aging total."""

    ledger: Literal["AR", "AP"]
    period: Period
    total: Money

    @property
    def reference(self) -> str:
        return f"{self.ledger} {self.period}"

    @property
    def amount(self) -> Decimal | None:
        return self.total

    @property
    def txn_date(self) -> date | None:
        return month_end(self.period)


class PeriodResult(Record):
    """A month's profit and loss (actual or budget), for the company or one business unit."""

    period: Period
    business_unit: str | None = Field(default=None, max_length=200)  # None: the whole company
    basis: Annotated[
        Literal["actual", "budget"],
        BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    ] = "actual"
    revenue: Money
    cogs: Money = Decimal("0.00")
    operating_expenses: Money = Decimal("0.00")
    operating_profit: Money | None = None  # if not given: revenue - cogs - operating expenses

    @model_validator(mode="after")
    def _derive_profit(self) -> "PeriodResult":
        if self.operating_profit is None:
            self.operating_profit = self.revenue - self.cogs - self.operating_expenses
        return self

    @property
    def reference(self) -> str:
        return f"{self.basis} {self.period} {self.business_unit or 'company'}"

    @property
    def counterparty(self) -> str | None:
        return self.business_unit

    @property
    def amount(self) -> Decimal | None:
        return self.revenue

    @property
    def txn_date(self) -> date | None:
        return month_end(self.period)


RECORD_MODELS: dict[RecordType, type[Record]] = {
    RecordType.VENDOR: Vendor,
    RecordType.BILL: Bill,
    RecordType.PURCHASE_ORDER: PurchaseOrder,
    RecordType.ACCOUNT: Account,
    RecordType.CUSTOMER: Customer,
    RecordType.INVOICE: Invoice,
    RecordType.PAYMENT: Payment,
    RecordType.EXPENSE: Expense,
    RecordType.ACCOUNT_BALANCE: AccountBalance,
    RecordType.SUBLEDGER_TOTAL: SubledgerTotal,
    RecordType.PERIOD_RESULT: PeriodResult,
}

RECORD_LABELS: dict[RecordType, str] = {
    RecordType.VENDOR: "Vendors",
    RecordType.BILL: "Bills (supplier invoices)",
    RecordType.PURCHASE_ORDER: "Purchase orders",
    RecordType.ACCOUNT: "Chart of accounts",
    RecordType.CUSTOMER: "Customers",
    RecordType.INVOICE: "Invoices (customer invoices)",
    RecordType.PAYMENT: "Customer payments",
    RecordType.EXPENSE: "Expenses (card, cash, check)",
    RecordType.ACCOUNT_BALANCE: "Account balances by month (trial balance)",
    RecordType.SUBLEDGER_TOTAL: "AR / AP subledger totals by month",
    RecordType.PERIOD_RESULT: "Profit and loss by month (actual or budget)",
}
