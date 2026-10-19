from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class ApInvoiceRun(AgentRunDetail, Base):
    """AP Invoice input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "ap_invoice_runs"

    # --- input ---
    supplier: Mapped[str | None] = mapped_column(String(200))
    invoice_number: Mapped[str | None] = mapped_column(String(100), index=True)
    legal_entity: Mapped[str | None] = mapped_column(String(200))
    invoice_total: Mapped[Decimal | None] = mapped_column(MONEY)
    po_authorized_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    received_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    tax_total: Mapped[Decimal | None] = mapped_column(MONEY)
    proposed_gl_account: Mapped[str | None] = mapped_column(String(50))

    # --- computed by the engine ---
    invoice_vs_po: Mapped[Decimal | None] = mapped_column(MONEY)
    invoice_vs_receipt: Mapped[Decimal | None] = mapped_column(MONEY)
