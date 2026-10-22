from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    money_field,
    money_setting,
    number_field,
    text_field,
    textarea_field,
)


class RevenueRecognitionInput(AgentInput):
    customer: str = text_field("Customer", max_length=200)
    contract_id: str = text_field("Contract ID", max_length=100, help="e.g. CTR-2026-091")
    contract_total: Decimal = money_field("Contract total", gt=Decimal(0))
    service_term_months: int = number_field("Service term (months)", ge=1, le=600)
    performance_obligations: str = textarea_field(
        "Performance obligations",
        required=True,
        help="What the customer gets, one per line, e.g. Hosting / Support",
    )
    variable_consideration: str | None = textarea_field(
        "Variable consideration / modifications",
        help="Discounts, rebates, usage fees, bonuses, or changes to the contract",
    )
    contract_clauses: str | None = textarea_field("Relevant contract clauses")


class RevenueRecognitionPolicy(PolicySettings):
    """Revenue recognition thresholds (defaults = policy revenue_recognition/v1)."""

    policy_review_amount: Decimal | None = money_setting(
        "Revenue policy review above",
        Decimal("100000.00"),
        help="Contracts above this need a revenue policy review. Empty: no review",
    )
