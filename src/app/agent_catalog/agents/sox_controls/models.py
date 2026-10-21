from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

PERCENT = Numeric()  # unbounded: invalid samples (flagged) can exceed 100%


class SoxControlsRun(AgentRunDetail, Base):
    """SOX control test input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "sox_controls_runs"

    # --- input ---
    control_id: Mapped[str | None] = mapped_column(String(100), index=True)
    control_owner: Mapped[str | None] = mapped_column(String(200))
    population_count: Mapped[int | None]
    items_tested: Mapped[int | None]
    exceptions_found: Mapped[int | None]
    evidence_references: Mapped[str | None] = mapped_column(Text)
    test_procedure: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    exception_rate_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    sample_coverage_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
