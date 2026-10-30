from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class FinancialCloseRun(AgentRunDetail, Base):
    """Financial Close input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "financial_close_runs"

    # --- input ---
    gl_account: Mapped[str | None] = mapped_column(String(100), index=True)
    close_period: Mapped[str | None] = mapped_column(String(7))
    gl_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    subledger_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    materiality_threshold: Mapped[Decimal | None] = mapped_column(MONEY)
    known_reconciling_items: Mapped[Decimal | None] = mapped_column(MONEY)
    proposed_adjustment_rationale: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    variance: Mapped[Decimal | None] = mapped_column(MONEY)
    unexplained_difference: Mapped[Decimal | None] = mapped_column(MONEY)
