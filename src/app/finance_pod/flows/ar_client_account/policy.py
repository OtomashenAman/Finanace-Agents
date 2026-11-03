"""Client account and credit settings. DEMO VALUES until GIA sets its own."""

from decimal import Decimal

from pydantic import BaseModel, Field


class ArcPolicy(BaseModel):
    demo_values: bool = True
    portal_link_days: int = Field(default=14, ge=1, le=60)
    sanctions_match_threshold: float = Field(default=0.92, ge=0.5, le=1)
    # Trade references a client must give to be considered for credit (none: deposit only)
    references_for_credit: int = Field(default=2, ge=0, le=5)
    # Risk score bands (0-100, higher is safer) and the most credit each may get
    low_risk_from: int = Field(default=70, ge=0, le=100)
    medium_risk_from: int = Field(default=50, ge=0, le=100)
    low_risk_limit: Decimal = Field(default=Decimal(25000), ge=0)
    medium_risk_limit: Decimal = Field(default=Decimal(10000), ge=0)
    # Payment terms (days) a client can be given: each must exist in the ERP as a payment
    # terms template ("Due on receipt" for 0, "Net N" otherwise)
    terms_days: tuple[int, ...] = (0, 30, 45)
    default_terms_days: int = 30
    deposit_pct: int = Field(default=50, ge=0, le=100)  # of each submission's fee estimate
    customer_group: str = "Commercial"
    home_country: str = "United States"  # its sales tax applies; elsewhere, export
    # The daily limit review: a finding when either is crossed
    review_utilisation_pct: int = Field(default=90, ge=1, le=100)
    review_overdue_days: int = Field(default=60, ge=1)
