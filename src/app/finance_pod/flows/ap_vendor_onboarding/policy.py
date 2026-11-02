"""Vendor onboarding settings. DEMO VALUES until GIA sets its own."""

from pydantic import BaseModel, Field


class VndPolicy(BaseModel):
    demo_values: bool = True
    portal_link_days: int = Field(default=7, ge=1, le=30)
    sanctions_match_threshold: float = Field(default=0.92, ge=0.5, le=1)
    supplier_group: str = "All Supplier Groups"  # where the new supplier goes in ERPNext
