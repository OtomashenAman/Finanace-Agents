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


class Basis(StrEnum):
    ACCRUAL = "Accrual"
    CASH = "Cash"


class Provenance(StrEnum):
    QUICKBOOKS_READONLY_EXPORT = "QUICKBOOKS_READONLY_EXPORT"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"  # fictional data, always labelled as demo


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
        return self
