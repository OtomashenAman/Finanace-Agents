from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    money_field,
    money_setting,
    number_field,
    signed_money_field,
    text_field,
    textarea_field,
)


class TreasuryCashInput(AgentInput):
    # The entity is the run's legal entity (picked when the run starts), not a form field
    currency: str = text_field("Currency", max_length=3, pattern=r"^[A-Za-z]{3}$", help="e.g. USD")
    opening_cash: Decimal = signed_money_field("Opening cash")
    expected_inflows: Decimal = money_field("Expected inflows")
    expected_outflows: Decimal = money_field("Expected outflows")
    minimum_liquidity_buffer: Decimal = money_field("Minimum liquidity buffer")
    forecast_horizon_days: int = number_field("Forecast horizon (days)", ge=1, le=730)
    permitted_funding_options: str | None = textarea_field(
        "Permitted funding options",
        help="e.g. revolver draw, intercompany loan: what may cover a shortfall",
    )


class TreasuryCashPolicy(PolicySettings):
    """Treasury thresholds (defaults = policy treasury_cash/v1)."""

    dual_authorization_amount: Decimal | None = money_setting(
        "Dual authorization above",
        Decimal("0.00"),
        help="Funding movements above this need two authorized signatories. Empty: no rule",
    )
    large_outflow_amount: Decimal | None = money_setting(
        "Large outflow review limit",
        None,
        help="Expected outflows above this are flagged for review. Empty: no limit",
    )
