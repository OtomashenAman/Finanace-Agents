from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)
RATE = Numeric(18, 8)


class IntercompanyRun(AgentRunDetail, Base):
    """Intercompany input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "intercompany_runs"

    # --- input ---
    sending_entity: Mapped[str | None] = mapped_column(String(200))
    receiving_entity: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str | None] = mapped_column(String(3))
    intercompany_ar: Mapped[Decimal | None] = mapped_column(MONEY)
    counterparty_ap: Mapped[Decimal | None] = mapped_column(MONEY)
    translation_rate: Mapped[Decimal | None] = mapped_column(RATE)
    matching_tolerance: Mapped[Decimal | None] = mapped_column(MONEY)
    transfer_pricing_notes: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    translated_ap: Mapped[Decimal | None] = mapped_column(MONEY)
    difference: Mapped[Decimal | None] = mapped_column(MONEY)
    nettable_amount: Mapped[Decimal | None] = mapped_column(MONEY)
