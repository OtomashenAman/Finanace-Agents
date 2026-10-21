from decimal import Decimal
from typing import Literal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    choice_field,
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


WHOLE_COMPANY = "Whole company"
# Metric -> PeriodResult field
METRICS = {
    "Revenue": "revenue",
    "Operating profit": "operating_profit",
    "Operating expenses": "operating_expenses",
}


class FpaPrefillParams(AgentInput):
    """Which unit, period and figure to take from the preparer's monthly P&L and budget."""

    business_unit: str = choice_field("Business unit", help="A QuickBooks class, or the company")
    forecast_period: str = choice_field("Forecast period", help="A month, quarter or year")
    metric: Literal["Revenue", "Operating profit", "Operating expenses"] = choice_field(
        "Metric", options=list(METRICS)
    )
