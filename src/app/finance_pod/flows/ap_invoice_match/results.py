"""What each L5 step of an invoice match records."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 3.2.1 Create invoice in ERP ----------------------------------------------------------


class InvoiceRecord(_Result):
    """3.2.1.a From validated data."""

    erp_invoice: str  # the ERPNext Purchase Invoice (a draft: posted after coding, AP-4)
    vendor_id: str
    bill_number: str
    bill_date: date | None
    total: Decimal
    lines: int
    po_backed: bool  # every line points at a PO line
    checks: list[str]  # what was validated


class SourceDocument(_Result):
    """3.2.1.b Attach source document."""

    document_id: uuid.UUID
    filename: str
    sha256: str


# --- 3.2.2 Duplicate guard -----------------------------------------------------------------


class PossibleDuplicate(_Result):
    bill_id: str
    bill_number: str | None
    total: Decimal
    doc_status: str
    number_similarity: float


class DuplicateSearch(_Result):
    """3.2.2.a Fuzzy match on number, amount."""

    compared: int
    matches: list[PossibleDuplicate]


class DuplicateDecision(_Result):
    """3.2.2.b Blocks and explains."""

    blocked: bool
    explanation: str


# --- 3.4.1 Three-way match / 3.4.2 Classify outcome -----------------------------------------


class LineMatch(_Result):
    item_code: str
    order_id: str | None
    order_line_id: str | None
    billed_qty: Decimal
    billed_rate: Decimal
    po_qty: Decimal | None
    po_rate: Decimal | None
    received_qty: Decimal | None  # accepted, on submitted receipts
    billed_before: Decimal  # quantity already billed on other posted invoices
    price_variance_pct: Decimal | None
    quantity_over: Decimal  # billed beyond what was received (net of earlier bills)
    status: Literal["match", "price", "quantity", "no_receipt", "no_po"]
    reason: str


class LineByLine(_Result):
    """3.4.1.a Line by line vs PO and receipt."""

    lines: list[LineMatch]


class Tolerances(_Result):
    """3.4.1.b Applies GIA tolerances."""

    price_pct: Decimal
    quantity: Decimal
    amount: Decimal
    policy_version: str


class SendToCoding(_Result):
    """3.4.2.a Match: send to coding."""

    sent: bool
    route: Literal["coding", "exception", "coding_non_po"]
    reason: str


class OpenException(_Result):
    """3.4.2.b Variance: open exception."""

    opened: bool
    variances: list[str]  # one line per line that doesn't match


# --- 3.5 Resolve variances ------------------------------------------------------------------


class ExceptionView(_Result):
    """3.5.1.a Shows PO, receipt, invoice."""

    rows: list[dict[str, str | None]]  # item, PO qty/rate, received, billed qty/rate, status


class VendorQuery(_Result):
    """3.5.1.b Drafts vendor query."""

    message_id: uuid.UUID | None  # None: the vendor has no verified email (asked otherwise)
    to_email: str | None


class BuyerDecision(_Result):
    """3.5.2.a Accept, credit or amend PO."""

    decision: Literal["accept", "credit", "amend_po"] = Field(title="Decision")
    note: str = Field(min_length=3, max_length=2000, title="Why")
    expected_credit: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=2, title="Credit expected (credit)"
    )

    @model_validator(mode="after")
    def _credit_amount(self) -> Self:
        if self.decision == "credit" and self.expected_credit is None:
            raise ValueError("Say how much credit the vendor is to issue.")
        return self


class LoopClosed(_Result):
    """3.5.3.a Re-matches; releases invoice."""

    rematched_on: str  # the snapshot the re-match used
    lines: list[LineMatch]
    released: bool
    how: str


# --- 3.6 Chase missing receipts -------------------------------------------------------------


class Nudge(_Result):
    """3.6.1.a Requests confirmation."""

    lines: list[str]  # what waits for a receipt
    receivers: list[str]  # who was asked (people holding the receiver capacity)


class ReceivedLine(_Result):
    order_line_id: str = Field(min_length=1, max_length=140)
    item_code: str = Field(min_length=1, max_length=140)
    received_qty: Decimal = Field(ge=0, max_digits=14, decimal_places=4)
    condition: Literal["ok", "damaged", "short"] = "ok"
    note: str | None = Field(default=None, max_length=500)


class ReceiptConfirmed(_Result):
    """3.6.2.a Posts receipt on mobile."""

    received_on: date = Field(title="Received on")
    lines: list[ReceivedLine] = Field(min_length=1, max_length=50)
