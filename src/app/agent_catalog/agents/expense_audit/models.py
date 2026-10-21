from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.common.models import Base

MONEY = Numeric(18, 2)


class ExpenseAuditRun(AgentRunDetail, Base):
    """Expense Audit input fields (nullable while the run is a draft) and computed results."""

    __tablename__ = "expense_audit_runs"

    # --- input ---
    employee: Mapped[str | None] = mapped_column(String(200))
    merchant: Mapped[str | None] = mapped_column(String(200))
    claim_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    policy_limit: Mapped[Decimal | None] = mapped_column(MONEY)
    receipt_total: Mapped[Decimal | None] = mapped_column(MONEY)
    receipt_provided: Mapped[bool | None]
    card_transaction_id: Mapped[str | None] = mapped_column(String(100), index=True)
    prior_card_transaction_ids: Mapped[str | None] = mapped_column(Text)

    # --- computed by the engine ---
    over_limit_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    claim_vs_receipt: Mapped[Decimal | None] = mapped_column(MONEY)
