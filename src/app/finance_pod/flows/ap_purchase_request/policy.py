"""The thresholds a purchase request is held to. These defaults are DEMO VALUES: GIA's own
purchasing threshold, quote count, PO approval limit and authority matrix replace them
(saved as new versions; each case records the version it was opened with)."""

from decimal import Decimal

from pydantic import BaseModel, Field


class Tier(BaseModel):
    min_amount: Decimal = Field(ge=0)
    approvers: list[str] = Field(min_length=1)  # capacities, in order


class PrqPolicy(BaseModel):
    demo_values: bool = True  # until GIA sets its own
    quote_threshold: Decimal = Field(default=Decimal(5000), ge=0)
    min_quotes: int = Field(default=3, ge=1, le=10)
    max_rfq_vendors: int = Field(default=5, ge=1, le=20)
    po_approval_limit: Decimal = Field(default=Decimal(25000), ge=0)
    budget_data_max_age_hours: int = Field(default=72, ge=1)
    authority_tiers: list[Tier] = [
        Tier(min_amount=Decimal(0), approvers=["budget_owner"]),
        Tier(min_amount=Decimal(25000), approvers=["budget_owner", "buyer"]),
    ]
