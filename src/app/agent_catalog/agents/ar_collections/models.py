from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class ArCollectionsRun(AgentRunDetail, Base):
    """AR Collections input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "ar_collections_runs"

    # --- input ---
    customer: Mapped[str | None] = mapped_column(String(200))
    open_balance: Mapped[Decimal | None] = mapped_column(MONEY)
    days_overdue: Mapped[int | None]
    previous_late_payments: Mapped[int | None]
    open_dispute: Mapped[bool | None]
    strategic_account: Mapped[bool | None]
    promise_to_pay: Mapped[str | None] = mapped_column(String(500))
    collection_notes: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    aging_bucket: Mapped[str | None] = mapped_column(String(10))
    priority_score: Mapped[int | None]
    next_action: Mapped[str | None] = mapped_column(String(50))
