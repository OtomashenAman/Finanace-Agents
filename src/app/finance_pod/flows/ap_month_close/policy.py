"""Close settings. DEMO VALUES until GIA sets its own."""

from decimal import Decimal

from pydantic import BaseModel, Field


class ApcPolicy(BaseModel):
    demo_values: bool = True
    close_day: int = Field(default=5, ge=1, le=28)  # accruals posted by this day of next month
    statement_min_balance: Decimal = Field(default=Decimal(500), ge=0)  # key vendors
    tolerance: Decimal = Field(default=Decimal("0.01"), ge=0)  # a difference smaller is none
