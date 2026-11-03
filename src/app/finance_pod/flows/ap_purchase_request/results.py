"""What each L5 step of a purchase request records (validated; part of what the release
binds). People fill in the PERSON steps; the agents produce the others from the snapshot."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Qty = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=4)]
Amount = Annotated[Decimal, Field(max_digits=18, decimal_places=6)]
Code = Annotated[str, Field(min_length=1, max_length=140)]
Note = Annotated[str, Field(min_length=1, max_length=2000)]


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 1.1.1 Describe the need (requester) --------------------------------------------------


class NeedLine(_Result):
    item_code: Code = Field(title="Catalogue item")
    quantity: Qty = Field(title="Quantity")
    estimated_unit_price: Amount | None = Field(default=None, title="Your estimate per unit")
    note: str | None = Field(default=None, max_length=500)


class Need(_Result):
    """1.1.1.a Item, quantity, purpose in form or chat."""

    channel: Literal["form", "chat"] = Field(title="Described in")
    purpose: str = Field(min_length=3, max_length=1000, title="What it's for")
    needed_by: date = Field(title="Needed by")
    lines: list[NeedLine] = Field(min_length=1, max_length=50)
    cost_centre_id: Code | None = Field(default=None, title="Cost centre (department)")
    lab_id: Code | None = Field(default=None, title="Lab")
    grant_id: Code | None = Field(default=None, title="Grant")


class QuoteUpload(_Result):
    """1.1.1.b Upload quote if available."""

    document_id: uuid.UUID | None = Field(default=None, title="Uploaded quote")
    none_available: bool = Field(default=False, title="No quote available")

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.document_id is None) == (not self.none_available):
            raise ValueError("Upload the quote, or say none is available (not both).")
        return self


# --- 1.1.2 Request agent enriches ---------------------------------------------------------


class Coding(_Result):
    """1.1.2.a Suggests cost centre, lab, grant (only ids the source lists)."""

    cost_centre_id: str | None
    lab_id: str | None
    grant_id: str | None
    sources: dict[str, Literal["requester", "history", "none"]]
    explanation: str


class PricedLine(_Result):
    item_code: str
    item_name: str
    quantity: Decimal
    unit_rate: Decimal | None
    rate_source: Literal["contract", "catalogue", "requester_estimate", "none"]
    contract_vendor_id: str | None = None
    catalogue_rate: Decimal | None = None
    contract_rate: Decimal | None = None
    estimate: Decimal | None = None
    variance_pct: Decimal | None = None  # the requester's estimate vs the rate used
    amount: Decimal | None
    account_id: str | None  # the item's expense account


class PriceCheck(_Result):
    """1.1.2.b Checks catalogue and contract prices."""

    lines: list[PricedLine]
    total: Decimal
    currency: str


class MissingData(_Result):
    """1.1.2.c Flags missing data before submit (it fails the step while anything is)."""

    missing: list[str]
    urgent: bool  # needed by a date already past: a buy before a PO exists (AP1.P2)


# --- 1.2.1 Budget agent checks --------------------------------------------------------------


class BudgetLine(_Result):
    against: Literal["cost_centre", "grant"]
    target_id: str
    account_id: str
    budget: Decimal | None  # None: no budget set for it
    actual: Decimal
    committed: Decimal  # open POs, approved requests not yet ordered
    this_request: Decimal
    remaining_after: Decimal | None
    over: bool


class BudgetCheck(_Result):
    """1.2.1.a Remaining budget or grant balance."""

    lines: list[BudgetLine]
    within_budget: bool
    data_as_of: str  # when the snapshot was taken


class GrantCheck(_Result):
    """1.2.1.b Grant allowability rules."""

    grant_id: str | None
    applies: bool
    allowed: bool
    problems: list[str]


class Routing(_Result):
    """1.2.1.c Routes by authority matrix."""

    amount: Decimal
    tier_from: Decimal
    approvers: list[str]  # capacities, in order
    quotes_required: bool
    quote_threshold: Decimal
    po_approval_required: bool
    po_approval_limit: Decimal


# --- 1.2.2 Budget owner decides -------------------------------------------------------------


class ImpactReviewed(_Result):
    """1.2.2.a Sees budget impact on screen."""

    reviewed: Literal[True] = Field(title="I reviewed the budget impact")


class BudgetDecision(_Result):
    """1.2.2.b Approves, rejects or queries."""

    decision: Literal["approve", "reject", "query"] = Field(
        title="Decision",
        description="Approve it; reject it (the request is closed); or query it (it goes back "
        "to the requester with your question).",
        json_schema_extra={"x-labels": {"approve": "Approve", "reject": "Reject",
                                        "query": "Query: send back with a question"}},
    )  # fmt: skip
    comment: str | None = Field(
        default=None, max_length=2000, title="Comment",
        description="Needed to reject or query, and to approve when the budget agent flagged "
        "the request.",
        examples=["Within the Q4 consumables plan"],
    )  # fmt: skip

    @model_validator(mode="after")
    def _say_why(self) -> Self:
        if self.decision != "approve" and not (self.comment and self.comment.strip()):
            raise ValueError("Say why when you reject or query a request.")
        return self


# --- 1.3.1 Sourcing agent ---------------------------------------------------------------------


class Candidate(_Result):
    vendor_id: str
    name: str
    has_email: bool
    contract_total: Decimal | None  # the request at this vendor's contract prices
    supplied_before: bool


class Excluded(_Result):
    vendor_id: str
    name: str
    reason: str


class Sourcing(_Result):
    """1.3.1.a Finds approved vendors and contracts."""

    candidates: list[Candidate]
    excluded: list[Excluded]


class RfqSent(_Result):
    vendor_id: str
    message_id: uuid.UUID


class QuoteRequests(_Result):
    """1.3.1.b Requests quotes above threshold."""

    threshold: Decimal
    amount: Decimal
    requested: list[RfqSent]
    skipped: list[Excluded]


class QuoteRow(_Result):
    vendor_id: str | None  # None: a vendor not in the source yet
    vendor_name: str
    source: Literal["erp", "recorded"]
    reference: str
    total: Decimal
    lead_time_days: int | None
    valid_till: date | None
    terms: str | None
    document_id: uuid.UUID | None = None
    rates: dict[str, Decimal]  # item code -> quoted unit rate


class Comparison(_Result):
    """1.3.1.c Compares quotes side by side."""

    quotes: list[QuoteRow]
    required: int  # how many quotes the policy asks for (0: below the threshold)
    cheapest: str | None  # quote reference
    fastest: str | None
    reference_price: Decimal  # the request at contract / catalogue prices


# --- 1.3.2 Buyer chooses ---------------------------------------------------------------------


class ComparisonReviewed(_Result):
    """1.3.2.a Reviews comparison."""

    reviewed: Literal[True] = Field(title="I reviewed the comparison")


class VendorChoice(_Result):
    """1.3.2.b Confirms vendor and terms."""

    vendor_id: str | None = Field(default=None, title="Vendor (from the vendor master)")
    new_vendor_name: str | None = Field(default=None, max_length=140, title="Or a new vendor")
    new_vendor_email: EmailStr | None = Field(default=None, title="New vendor's contact email")
    quote_reference: str | None = Field(default=None, max_length=140, title="Quote chosen")
    terms: str = Field(min_length=2, max_length=500, title="Terms agreed")
    reason: str | None = Field(default=None, max_length=2000, title="Why (if not the cheapest)")

    @model_validator(mode="after")
    def _one_vendor(self) -> Self:
        if (self.vendor_id is None) == (self.new_vendor_name is None):
            raise ValueError("Choose a vendor from the master, or name a new one (not both).")
        if self.new_vendor_name and not self.new_vendor_email:
            raise ValueError("Give the new vendor's contact email for the onboarding invitation.")
        return self


# --- 1.6.1 PO agent / 1.6.2 Buyer approves -------------------------------------------------


class PoLine(_Result):
    item_code: str
    quantity: Decimal
    rate: Decimal
    rate_source: Literal["quote", "contract", "catalogue"]
    amount: Decimal
    needed_by: date


class DraftPo(_Result):
    """1.6.1.a Drafts PO from approved request."""

    vendor_id: str
    lines: list[PoLine]
    total: Decimal
    currency: str


class PoLineCoding(_Result):
    item_code: str
    cost_centre_id: str | None
    lab_id: str | None
    grant_id: str | None
    account_id: str | None


class PoCoding(_Result):
    """1.6.1.b Applies coding and terms."""

    lines: list[PoLineCoding]
    terms: str


class PoApproval(_Result):
    """1.6.2.a Approves POs above limit."""

    approved: Literal[True] = Field(title="I approve this PO")
    note: str | None = Field(default=None, max_length=2000, title="Note",
                             description="Optional: anything the next person should know.",
                             examples=["Within the grant's equipment budget"])  # fmt: skip


class Acknowledgement(_Result):
    how: Literal["reply", "phone", "vendor_portal", "other"]
    note: str
    logged_by: str
    logged_at: str


class PoSent(_Result):
    """1.6.1.c Sends PO; logs acknowledgement."""

    erp_po: str
    task_id: uuid.UUID
    message_id: uuid.UUID
    acknowledgement: Acknowledgement


class RecordQuotePayload(BaseModel):
    """A vendor's quote that came by email or phone, with its document as evidence."""

    vendor_id: str | None = Field(default=None, max_length=140)
    vendor_name: str = Field(min_length=1, max_length=140)
    reference: str = Field(min_length=1, max_length=140)
    total: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    valid_till: date | None = None
    terms: str | None = Field(default=None, max_length=500)
    document_id: uuid.UUID
    rates: dict[str, Decimal] = {}


class AcknowledgePayload(BaseModel):
    how: Literal["reply", "phone", "vendor_portal", "other"]
    note: Note
