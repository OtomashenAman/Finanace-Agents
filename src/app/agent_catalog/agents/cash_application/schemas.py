from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    bool_field,
    money_field,
    money_setting,
    text_field,
    textarea_field,
)


class CashApplicationInput(AgentInput):
    customer: str = text_field("Customer", max_length=200)
    payment_reference: str = text_field(
        "Payment/remittance reference", max_length=100, help="e.g. the wire or check number"
    )
    payment_amount: Decimal = money_field("Payment amount", gt=Decimal(0))
    candidate_invoice_number: str = text_field("Candidate invoice number", max_length=100)
    invoice_open_amount: Decimal = money_field("Invoice open amount", gt=Decimal(0))
    reference_verified: bool = bool_field(
        "Reference verified", help="The payment reference was checked against the invoice"
    )
    remittance_advice: str | None = textarea_field("Remittance advice")


class CashApplicationPolicy(PolicySettings):
    """Cash application thresholds (defaults = policy cash_application/v1)."""

    match_tolerance: Decimal = money_setting(
        "Match tolerance",
        Decimal("0.00"),
        help="Largest payment vs invoice difference still applied as a full match",
    )
    deduction_review_amount: Decimal | None = money_setting(
        "Deduction review threshold",
        Decimal("0.00"),
        help="Short payments above this must be classified as a deduction. Empty: no review",
    )
