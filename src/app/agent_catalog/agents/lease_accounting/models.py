from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)
PERCENT_INPUT = Numeric(9, 4)


class LeaseAccountingRun(AgentRunDetail, Base):
    """Lease Accounting input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "lease_accounting_runs"

    # --- input ---
    lessor: Mapped[str | None] = mapped_column(String(200), index=True)
    leased_asset: Mapped[str | None] = mapped_column(String(200))
    monthly_payment: Mapped[Decimal | None] = mapped_column(MONEY)
    remaining_term_months: Mapped[int | None]
    annual_discount_rate: Mapped[Decimal | None] = mapped_column(PERCENT_INPUT)
    initial_direct_costs: Mapped[Decimal | None] = mapped_column(MONEY)
    renewal_termination_options: Mapped[str | None] = mapped_column(Text)
    lease_clauses: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    lease_liability: Mapped[Decimal | None] = mapped_column(MONEY)
    right_of_use_asset: Mapped[Decimal | None] = mapped_column(MONEY)
    total_interest: Mapped[Decimal | None] = mapped_column(MONEY)
