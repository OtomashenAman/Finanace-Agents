from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FinanceSettingsOut(BaseModel):
    currency: str
    purchasing_threshold: Decimal
    min_quotes: int
    allow_self_approval: bool
    price_tolerance_pct: Decimal
    price_tolerance_amount: Decimal
    qty_tolerance_pct: Decimal
    payment_horizon_days: int
    cash_available: Decimal | None
    unusual_payment_amount: Decimal
    bank_change_days: int
    max_new_client_limit: Decimal
    credit_review_days: int
    updated_at: datetime | None


class FinanceSettingsUpdate(BaseModel):
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    purchasing_threshold: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    min_quotes: int = Field(ge=1, le=10)
    allow_self_approval: bool
    # Phase 3 matching tolerances (omitted: left as they are)
    price_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    price_tolerance_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    qty_tolerance_pct: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    # Payments (omitted: left as they are; cash_available null = not checked is set via
    # clear_cash_available)
    payment_horizon_days: int | None = Field(default=None, ge=0, le=90)
    cash_available: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    clear_cash_available: bool = False
    unusual_payment_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    bank_change_days: int | None = Field(default=None, ge=0, le=365)
    # Receivables (omitted: left as they are)
    max_new_client_limit: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    credit_review_days: int | None = Field(default=None, ge=30, le=1095)
