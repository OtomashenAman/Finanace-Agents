"""What each L5 step of a client account set-up records."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 1.1.1 Client applies (through the portal) -----------------------------------------------


class TradeReference(_Result):
    company: str = Field(
        min_length=2, max_length=140, title="Company", examples=["Brilliant Gems LLC"]
    )
    contact_email: EmailStr = Field(title="Contact email", examples=["ap@brilliantgems.com"])


class Application(_Result):
    """1.1.1.a Completes portal form."""

    legal_name: str = Field(min_length=2, max_length=140, title="Legal name",
                            description="As on the tax form and the registration papers.",
                            examples=["Lumen Gem Traders LLC"])  # fmt: skip
    trading_name: str | None = Field(
        default=None,
        max_length=140,
        title="Trading name",
        description="Only if it trades under another name.",
    )
    tax_id: str | None = Field(default=None, max_length=30, title="Tax ID (EIN, or VAT abroad)",
                               description="A US EIN looks like 12-3456789.",
                               examples=["84-7654321"])  # fmt: skip
    country: str = Field(min_length=2, max_length=60, title="Country",
                         description="Sets the sales tax: the home country, or export.",
                         examples=["United States"])  # fmt: skip
    address: str = Field(
        min_length=5,
        max_length=500,
        title="Address",
        examples=["580 Fifth Avenue, New York, NY 10036"],
    )
    billing_email: EmailStr = Field(title="Where invoices go",
                                    description="Invoices and statements go to this address.",
                                    examples=["ap@lumengem.com"])  # fmt: skip
    established_year: int | None = Field(default=None, ge=1800, le=2100, title="Established",
                                         description="The year the company started.",
                                         examples=[2015])  # fmt: skip
    requested_limit: Decimal = Field(
        ge=0, max_digits=14, decimal_places=2, title="Credit limit requested",
        description="The most the client wants to owe at a time. 0 means it pays on deposit.",
        examples=["20000"],
    )  # fmt: skip
    requested_terms_days: int = Field(
        ge=0, le=120, title="Payment terms requested (days)",
        description="Days to pay after the invoice, e.g. 30. 0 means due on receipt.",
        examples=[30],
    )  # fmt: skip
    trade_references: list[TradeReference] = Field(
        default=[], max_length=5, title="Trade references",
        description="Companies that give the client credit today. Two are needed for credit "
        "terms; none means it starts on deposit.",
    )  # fmt: skip


class DocumentsUploaded(_Result):
    """1.1.1.b Uploads documents."""

    tax_form_id: uuid.UUID | None = Field(
        default=None, title="Tax form (W-9 / W-8)",
        description="Upload it under Documents (kind: Tax form), then choose it here.",
        json_schema_extra={"x-document": ["tax_form"]},
    )  # fmt: skip
    registration_ids: list[uuid.UUID] = Field(
        default=[], title="Registration / compliance papers",
        description="Upload them under Documents (kind: Compliance), then tick them here.",
        json_schema_extra={"x-document": ["compliance"]},
    )  # fmt: skip


# --- 1.1.2 Onboarding agent -----------------------------------------------------------------


class DocumentsChecked(_Result):
    """1.1.2.a Reads and validates documents."""

    tax_form: Literal["W-9", "W-8BEN", "W-8BEN-E", "unknown", "missing"]
    name_on_form: str | None
    tax_id_on_form: str | None
    name_matches: bool
    tax_id_matches: bool
    tax_id_checks: list[str]  # problems with its form (empty: well formed)
    registration_documents: int


class SanctionsHit(_Result):
    screened_name: str
    listed_name: str
    entry_id: str
    programs: str | None
    score: float


class Screening(_Result):
    """1.1.2.b Runs compliance screening."""

    sanctions_list: str
    sanctions_loaded_at: datetime
    screened: list[str]
    hits: list[SanctionsHit]  # each one is a blocking review task until cleared
    not_checked: str


class Gaps(_Result):
    """1.1.2.c Flags gaps to client."""

    gaps: list[str]  # empty: nothing missing
    message_id: uuid.UUID | None = None  # the email that told the client


# --- 1.2.1 Credit agent / 1.2.2 Credit controller ------------------------------------------


class RiskFactor(_Result):
    factor: str
    points: int


class RiskScore(_Result):
    """1.2.1.a Scores risk from data."""

    score: int = Field(ge=0, le=100)  # higher is safer
    band: Literal["low", "medium", "high"]
    factors: list[RiskFactor]
    history: str  # what the books say about this client (a new one has none)


class CreditProposal(_Result):
    """1.2.1.b Proposes limit or deposit."""

    deposit_only: bool
    credit_limit: Decimal | None
    terms_days: int
    deposit_pct: int | None
    reason: str
    policy_version: str


class CreditDecision(_Result):
    """1.2.2.a Approves terms and limit."""

    decision: Literal["approve_credit", "deposit_only", "decline"] = Field(
        title="Decision",
        description="See the credit agent's proposal above.",
        json_schema_extra={"x-labels": {"approve_credit": "Approve credit",
                                        "deposit_only": "Deposit only (no credit)",
                                        "decline": "Decline the account"}},
    )  # fmt: skip
    credit_limit: Decimal | None = Field(
        default=None, gt=0, max_digits=14, decimal_places=2, title="Credit limit",
        description="Only when approving credit. Above the agent's proposal needs a reason.",
        examples=["15000"],
    )  # fmt: skip
    terms_days: int | None = Field(
        default=None, ge=0, le=120, title="Payment terms (days)",
        description="Only when approving credit: 0, 30 or 45 (the ERP's payment terms).",
        examples=[30],
    )  # fmt: skip
    reason: str | None = Field(
        default=None, max_length=2000, title="Reason",
        description="Needed to decline, or to give more than the agent proposed.",
        examples=["Parent company guarantee"],
    )  # fmt: skip

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.decision == "approve_credit" and (
            self.credit_limit is None or self.terms_days is None
        ):
            raise ValueError("Give the credit limit and payment terms you approve.")
        if self.decision == "decline" and not (self.reason and self.reason.strip()):
            raise ValueError("Say why the account is declined.")
        return self


# --- 1.3 Create account ---------------------------------------------------------------------


class ClientCreated(_Result):
    """1.3.1.a Creates client in both systems."""

    erp_customer: str
    verified_on: str  # the snapshot that holds it
    lab_system: str  # not connected yet: stated, never implied


class InSync(_Result):
    """1.3.1.b Keeps them in sync."""

    checked: list[str]  # the fields compared with what was approved
    differences: list[str]


class LimitReview(_Result):
    """1.3.2.a Reviews limits as history builds."""

    as_of: date
    credit_limit: Decimal | None
    outstanding: Decimal
    utilisation_pct: Decimal | None
    oldest_overdue_days: int
    suggestion: Literal["keep", "review"]
    reason: str
