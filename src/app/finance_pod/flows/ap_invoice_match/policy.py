"""Matching tolerances. DEMO VALUES until GIA sets its own (each case records the version)."""

from decimal import Decimal

from pydantic import BaseModel, Field


class ApmPolicy(BaseModel):
    demo_values: bool = True
    price_tolerance_pct: Decimal = Field(default=Decimal(2), ge=0, le=100)  # per line
    quantity_tolerance: Decimal = Field(default=Decimal(0), ge=0)  # units over the receipt
    amount_tolerance: Decimal = Field(default=Decimal(5), ge=0)  # a line's value difference
    duplicate_number_similarity: float = Field(default=0.85, ge=0.5, le=1)
    held_review_days: int = Field(default=7, ge=1, le=60)  # AP3.R3: held invoices reviewed weekly
