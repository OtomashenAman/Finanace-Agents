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


class ExpenseAuditInput(AgentInput):
    employee: str = text_field("Employee", max_length=200)
    merchant: str = text_field("Merchant", max_length=200)
    claim_amount: Decimal = money_field("Claim amount", gt=Decimal(0))
    policy_limit: Decimal = money_field("Policy limit", help="Limit for this expense category")
    receipt_total: Decimal | None = money_field("Receipt total", required=False)
    receipt_provided: bool = bool_field("Receipt provided")
    card_transaction_id: str | None = text_field(
        "Card transaction ID", required=False, max_length=100
    )
    prior_card_transaction_ids: str | None = textarea_field(
        "Prior card transaction IDs",
        max_length=4000,
        help="Transactions already claimed, separated by commas or new lines",
    )


class ExpenseAuditPolicy(PolicySettings):
    """Expense audit thresholds (defaults = policy expense_audit/v1)."""

    receipt_tolerance: Decimal = money_setting(
        "Receipt match tolerance",
        Decimal("0.00"),
        help="Largest claim vs receipt difference still treated as a match",
    )
