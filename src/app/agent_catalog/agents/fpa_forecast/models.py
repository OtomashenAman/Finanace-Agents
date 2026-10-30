from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)
PERCENT_INPUT = Numeric(9, 4)
PERCENT = Numeric()  # unbounded: a tiny budget can make the variance % huge
WIDE_MONEY = Numeric(20, 2)  # results of two signed MONEY values can exceed MONEY


class FpaForecastRun(AgentRunDetail, Base):
    """FP&A input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "fpa_forecast_runs"

    # --- input ---
    business_unit: Mapped[str | None] = mapped_column(String(200))
    forecast_period: Mapped[str | None] = mapped_column(String(20))
    actual_value: Mapped[Decimal | None] = mapped_column(MONEY)
    budget_value: Mapped[Decimal | None] = mapped_column(MONEY)
    scenario_volume_pct: Mapped[Decimal | None] = mapped_column(PERCENT_INPUT)
    scenario_price_pct: Mapped[Decimal | None] = mapped_column(PERCENT_INPUT)
    scenario_cost_pct: Mapped[Decimal | None] = mapped_column(PERCENT_INPUT)
    planning_assumptions: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    variance: Mapped[Decimal | None] = mapped_column(WIDE_MONEY)
    variance_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    scenario_value: Mapped[Decimal | None] = mapped_column(WIDE_MONEY)
