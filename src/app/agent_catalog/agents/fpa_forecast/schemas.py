from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    percent_field,
    percent_setting,
    signed_money_field,
    text_field,
    textarea_field,
)


class FpaForecastInput(AgentInput):
    business_unit: str = text_field("Business unit", max_length=200)
    forecast_period: str = text_field("Forecast period", max_length=20, help="e.g. Q4 2026")
    actual_value: Decimal = signed_money_field("Actual value")
    budget_value: Decimal = signed_money_field("Budget value")
    scenario_volume_pct: Decimal = percent_field(
        "Scenario volume change (%)", help="Applied to the actual value"
    )
    scenario_price_pct: Decimal = percent_field(
        "Scenario price change (%)", help="Applied after the volume change"
    )
    scenario_cost_pct: Decimal = percent_field(
        "Scenario cost change (%)", help="Cost increase as a % of the actual value"
    )
    planning_assumptions: str | None = textarea_field("Planning assumptions")


class FpaForecastPolicy(PolicySettings):
    """FP&A thresholds (defaults = policy fpa_forecast/v1)."""

    variance_materiality_pct: Decimal | None = percent_setting(
        "Variance materiality",
        Decimal("10"),
        help="Actual vs budget variance beyond this % needs an explanation. Empty: no check",
    )
    scenario_review_pct: Decimal | None = percent_setting(
        "Scenario change review limit",
        Decimal("25"),
        help="Any scenario driver beyond this % is flagged as unusual. Empty: no check",
    )
