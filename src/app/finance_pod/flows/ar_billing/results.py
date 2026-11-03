"""What each L5 step of a billing case records."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 3.1 Build the invoice -------------------------------------------------------------------


class Triggered(_Result):
    """3.1.1.a On report-issued event."""

    submission_id: str
    client_id: str
    submitted_on: date
    report_issued_on: date


class PerformedLine(_Result):
    submission_line_id: str
    item_code: str
    item_name: str
    qty: Decimal
    lab_rate: Decimal  # the rate the lab system holds (not the fee: 3.2.1 sets that)
    added: bool  # added in the lab after the client submitted


class Performed(_Result):
    """3.1.2.a Services actually performed."""

    lines: list[PerformedLine]
    already_billed: list[str]  # lines an earlier invoice covered (left out)


class AccountTerms(_Result):
    """3.1.2.b Client and account terms."""

    client_name: str
    status: str
    terms_days: int | None
    deposit_only: bool
    credit_limit: Decimal | None
    open_balance: Decimal
    currency: str
    email: str | None
    tax_category: str | None


# --- 3.2 Price and check ---------------------------------------------------------------------


class PricedLine(_Result):
    submission_line_id: str
    item_code: str
    qty: Decimal
    schedule_rate: Decimal | None  # the published fee
    rate: Decimal  # what the invoice charges
    source: Literal["schedule", "client price", "contract discount", "no fee"]
    discount_pct: Decimal | None
    amount: Decimal


class Priced(_Result):
    """3.2.1.a Fees, discounts, contract prices."""

    lines: list[PricedLine]
    net_total: Decimal


class Taxed(_Result):
    """3.2.1.b Currency and tax."""

    currency: str
    tax_rule: str | None
    tax_category: str | None
    rate_pct: Decimal
    tax: Decimal
    total: Decimal


class EstimateCheck(_Result):
    """3.2.2.a Compare to fee estimate."""

    fee_estimate: Decimal | None
    net_total: Decimal
    difference: Decimal | None
    difference_pct: Decimal | None
    within_tolerance: bool
    tolerance_pct: Decimal


class Flags(_Result):
    """3.2.2.b Flag unusual items."""

    flags: list[str]  # empty: nothing for a billing analyst to look at


# --- 3.3 Exceptions --------------------------------------------------------------------------


class FlagsReviewed(_Result):
    """3.3.1.a Reviews flagged invoices."""

    reviewed: Literal[True] = Field(title="I reviewed the flags")
    note: str = Field(min_length=3, max_length=2000, title="What I found",
                      description="What the flags turned out to be, for the record.",
                      examples=["The client asked for inscriptions at intake"])  # fmt: skip


class Override(_Result):
    item_code: str = Field(min_length=1, max_length=140, title="Item",
                           description="The item's code as the invoice shows it.",
                           examples=["SV-LASER"])  # fmt: skip
    rate: Decimal = Field(
        ge=0, max_digits=14, decimal_places=2, title="Rate on this invoice", examples=["30"]
    )
    reason: str = Field(
        min_length=3, max_length=500, title="Why", examples=["Agreed with the client at intake"]
    )


class Overrides(_Result):
    """3.3.1.b Approves price overrides."""

    overrides: list[Override] = Field(
        default=[], max_length=50, title="Price overrides",
        description="Only to change a rate on this invoice (the fee schedule stays as it is). "
        "Leave empty to keep the agent's rates.",
    )  # fmt: skip

    @model_validator(mode="after")
    def _once(self) -> Self:
        codes = [o.item_code for o in self.overrides]
        if len(codes) != len(set(codes)):
            raise ValueError("One override per item.")
        return self


# --- 3.5 Deliver -----------------------------------------------------------------------------


class Delivered(_Result):
    """3.5.1.a Posts invoice; portal and email."""

    erp_invoice: str
    total: Decimal
    message_id: uuid.UUID
    portal: str  # no client portal for invoices yet: stated, never implied


class OnStatement(_Result):
    """3.5.1.b Monthly statements automatic."""

    statement_month: str  # YYYY-MM: the monthly statement this invoice appears on
    how: str
