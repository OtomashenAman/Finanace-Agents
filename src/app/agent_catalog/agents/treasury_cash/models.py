from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class TreasuryCashRun(AgentRunDetail, Base):
    """Treasury input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "treasury_cash_runs"

    # --- input ---
    currency: Mapped[str | None] = mapped_column(String(3))
    opening_cash: Mapped[Decimal | None] = mapped_column(MONEY)
    expected_inflows: Mapped[Decimal | None] = mapped_column(MONEY)
    expected_outflows: Mapped[Decimal | None] = mapped_column(MONEY)
    minimum_liquidity_buffer: Mapped[Decimal | None] = mapped_column(MONEY)
    forecast_horizon_days: Mapped[int | None]
    permitted_funding_options: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    closing_cash: Mapped[Decimal | None] = mapped_column(MONEY)
    funding_gap: Mapped[Decimal | None] = mapped_column(MONEY)
