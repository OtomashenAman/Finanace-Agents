import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, TimestampMixin

SETTINGS_ROW = 1
DEFAULT_THRESHOLD = Decimal("10000.00")
DEFAULT_MIN_QUOTES = 3
DEFAULT_PRICE_PCT = Decimal("2.00")
DEFAULT_PRICE_AMOUNT = Decimal("1.00")


class FinancePodSettings(TimestampMixin, Base):
    """Finance POD controls (a single row). Without the row the defaults apply."""

    __tablename__ = "fpod_settings"
    __table_args__ = (
        CheckConstraint(f"id = {SETTINGS_ROW}", name="single_row"),
        CheckConstraint("purchasing_threshold >= 0", name="threshold"),
        CheckConstraint("min_quotes BETWEEN 1 AND 10", name="min_quotes"),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    id: Mapped[int] = mapped_column(primary_key=True, default=SETTINGS_ROW)
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    # Quotes are required at or above this amount (business rule of Phase 1)
    purchasing_threshold: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=DEFAULT_THRESHOLD, server_default=str(DEFAULT_THRESHOLD)
    )
    min_quotes: Mapped[int] = mapped_column(
        default=DEFAULT_MIN_QUOTES, server_default=str(DEFAULT_MIN_QUOTES)
    )
    # Off: separation-of-duties rules hold between admin accounts (requester != approver,
    # vendor verifier != activator). On (single-admin demo): allowed, and marked in the audit
    allow_self_approval: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # Phase 3 matching tolerances, per line: an invoice price over the PO price by more than
    # max(pct of the PO price, amount per unit) is a price variance; a quantity over what was
    # received (and not yet invoiced) by more than qty pct is a quantity variance
    price_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=DEFAULT_PRICE_PCT, server_default=str(DEFAULT_PRICE_PCT)
    )
    price_tolerance_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=DEFAULT_PRICE_AMOUNT, server_default=str(DEFAULT_PRICE_AMOUNT)
    )
    qty_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), server_default="0.00"
    )
    # Payments: invoices due within this many days go in the next run
    payment_horizon_days: Mapped[int] = mapped_column(default=7, server_default="7")
    # The cash view the run is checked against (None: not checked)
    cash_available: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # A payment at or above this is flagged as unusual for treasury
    unusual_payment_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("25000.00"), server_default="25000.00"
    )
    # Bank details changed within this many days: call-back before the payment goes
    bank_change_days: Mapped[int] = mapped_column(default=30, server_default="30")
    # Receivables: the most credit the credit agent proposes for a new client (the credit
    # controller may approve more), and how often each client's terms are reviewed
    max_new_client_limit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("50000.00"), server_default="50000.00"
    )
    credit_review_days: Mapped[int] = mapped_column(default=365, server_default="365")
    # Billing: an invoice more than this % over the intake estimate goes to the analyst
    estimate_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("10.00"), server_default="10.00"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
