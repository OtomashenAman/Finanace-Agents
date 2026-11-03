"""Billing settings. DEMO VALUES until GIA sets its own."""

from decimal import Decimal

from pydantic import BaseModel, Field


class ArbPolicy(BaseModel):
    demo_values: bool = True
    # The invoice may differ from the fee estimate the client saw by this much before a
    # billing analyst looks at it
    estimate_tolerance_pct: Decimal = Field(default=Decimal(5), ge=0, le=100)
    # A line above this many units is unusual for one submission
    unusual_qty: Decimal = Field(default=Decimal(100), gt=0)
