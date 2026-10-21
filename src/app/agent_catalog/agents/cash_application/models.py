from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class CashApplicationRun(AgentRunDetail, Base):
    """Cash Application input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "cash_application_runs"

    # --- input ---
    customer: Mapped[str | None] = mapped_column(String(200))
    payment_reference: Mapped[str | None] = mapped_column(String(100), index=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    candidate_invoice_number: Mapped[str | None] = mapped_column(String(100))
    invoice_open_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    reference_verified: Mapped[bool | None]
    remittance_advice: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    short_payment: Mapped[Decimal | None] = mapped_column(MONEY)  # negative: overpayment
