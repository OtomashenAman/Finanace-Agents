from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    money_field,
    number_field,
    number_setting,
    percent_field,
    percent_setting,
    text_field,
    textarea_field,
)


class LeaseAccountingInput(AgentInput):
    lessor: str = text_field("Lessor", max_length=200)
    leased_asset: str = text_field("Leased asset", max_length=200, help="e.g. Headquarters space")
    monthly_payment: Decimal = money_field("Monthly payment", gt=Decimal(0))
    remaining_term_months: int = number_field("Remaining term in months", ge=1, le=600)
    annual_discount_rate: Decimal = percent_field(
        "Annual discount rate (%)",
        ge=Decimal(0),
        le=Decimal(100),
        help="The rate implicit in the lease, or the incremental borrowing rate",
    )
    initial_direct_costs: Decimal | None = money_field("Initial direct costs", required=False)
    renewal_termination_options: str | None = textarea_field("Renewal / termination options")
    lease_clauses: str | None = textarea_field("Lease contract clauses")


class LeaseAccountingPolicy(PolicySettings):
    """Lease accounting thresholds (defaults = policy lease_accounting/v1)."""

    short_term_months: int | None = number_setting(
        "Short-term lease up to (months)",
        12,
        help="Leases this short may use the short-term exemption. Empty: no exemption",
    )
    minimum_discount_rate: Decimal | None = percent_setting(
        "Lowest expected discount rate (%)",
        Decimal("1"),
        help="Rates below this are flagged for review. Empty: no check",
    )
    maximum_discount_rate: Decimal | None = percent_setting(
        "Highest expected discount rate (%)",
        Decimal("15"),
        help="Rates above this are flagged for review. Empty: no check",
    )
