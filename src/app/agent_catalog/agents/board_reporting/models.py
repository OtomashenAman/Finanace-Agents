from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)
PERCENT = Numeric()  # unbounded: a tiny prior period can make growth huge


class BoardReportingRun(AgentRunDetail, Base):
    """Board Reporting input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "board_reporting_runs"

    # --- input ---
    report_name: Mapped[str | None] = mapped_column(String(200))
    reporting_period: Mapped[str | None] = mapped_column(String(20))
    reported_revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    prior_period_revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    operating_profit: Mapped[Decimal | None] = mapped_column(MONEY)
    source_dataset_id: Mapped[str | None] = mapped_column(String(200))
    known_disclosures: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    revenue_change: Mapped[Decimal | None] = mapped_column(MONEY)
    revenue_growth_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    operating_margin_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
