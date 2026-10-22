from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class RevenueRecognitionRun(AgentRunDetail, Base):
    """Revenue Recognition input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "revenue_recognition_runs"

    # --- input ---
    customer: Mapped[str | None] = mapped_column(String(200))
    contract_id: Mapped[str | None] = mapped_column(String(100), index=True)
    contract_total: Mapped[Decimal | None] = mapped_column(MONEY)
    service_term_months: Mapped[int | None]
    performance_obligations: Mapped[str | None] = mapped_column(Text)
    variable_consideration: Mapped[str | None] = mapped_column(Text)
    contract_clauses: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    monthly_revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    obligation_count: Mapped[int | None]
