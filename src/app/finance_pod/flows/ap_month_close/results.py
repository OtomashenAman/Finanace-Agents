"""What each L5 step of a month-end close records."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 6.1.1 Accruals --------------------------------------------------------------------------


class UnbilledLine(_Result):
    order_id: str
    order_line_id: str
    vendor_id: str
    item_code: str
    stock_item: bool
    received_qty: Decimal
    billed_qty: Decimal
    unbilled_qty: Decimal
    rate: Decimal
    value: Decimal
    account_id: str | None
    cost_centre_id: str | None
    lab_id: str | None
    grant_id: str | None


class ReceiptsNotInvoiced(_Result):
    """6.1.1.a Lists receipts not invoiced."""

    period_end: date
    lines: list[UnbilledLine]
    stock_total: Decimal  # already in Stock Received But Not Billed (perpetual inventory)
    non_stock_total: Decimal  # services and non-stock items: nothing in the ledger yet


class JournalLine(_Result):
    account_id: str
    debit: Decimal
    credit: Decimal
    cost_centre_id: str | None = None
    lab_id: str | None = None
    grant_id: str | None = None


class AccrualProposal(_Result):
    """6.1.1.b Proposes accrual journal (the controller posts it, AP6.G1)."""

    posting_date: date | None
    reversal_date: date | None
    lines: list[JournalLine]  # empty: nothing to accrue beyond what the ledger holds
    total: Decimal
    note: str


# --- 6.1.2 Reconcile --------------------------------------------------------------------------


class Comparison(_Result):
    ledger: Literal["payable", "received_not_billed"]
    account_id: str | None
    subledger: Decimal  # what the documents say
    ledger_balance: Decimal  # what the GL says
    difference: Decimal  # ledger - subledger


class SubledgerVsLedger(_Result):
    """6.1.2.a Subledger vs ledger daily."""

    as_of: date
    comparisons: list[Comparison]


class Difference(_Result):
    ledger: str
    amount: Decimal
    voucher: str | None
    explanation: str


class Explanation(_Result):
    """6.1.2.b Explains differences."""

    items: list[Difference]
    unexplained: Decimal  # what no posting accounts for (0: fully explained)
    held_invoices: list[str]  # invoices still held in matching (AP-3), not in the subledger


# --- 6.1.3 Vendor statements -----------------------------------------------------------------


class StatementGap(_Result):
    reference: str
    kind: Literal["not_in_books", "not_on_statement", "amount_differs"]
    statement_amount: Decimal | None
    books_amount: Decimal | None


class StatementRead(_Result):
    document_id: uuid.UUID
    vendor_id: str | None  # None: no vendor of the master named in it
    closing_balance: Decimal | None
    books_balance: Decimal | None
    lines_read: int
    gaps: list[StatementGap]


class StatementCheck(_Result):
    """6.1.3.a Reads statements; flags gaps."""

    statements: list[StatementRead]
    missing: list[str]  # key vendors (balance above the policy's) without a statement
    gaps: int


# --- 6.2 Review and sign off -------------------------------------------------------------------


class Review(_Result):
    """6.2.1.a Accruals and exceptions."""

    accruals_reviewed: Literal[True] = Field(title="I reviewed the accruals")
    exceptions_reviewed: Literal[True] = Field(
        title="I reviewed the differences, statement gaps and held invoices"
    )
    comment: str | None = Field(
        default=None, max_length=2000, title="Comment",
        description="Needed when a difference is unexplained: what it is and who follows up.",
        examples=["Rebate journal explains the Creditors difference"],
    )  # fmt: skip


class SignOff(_Result):
    """6.2.2.a Approve; evidence auto-filed."""

    approved: Literal[True] = Field(title="I sign off this month's AP close")
    comment: str | None = Field(
        default=None,
        max_length=2000,
        title="Comment",
        description="Optional: anything for the auditors.",
    )
