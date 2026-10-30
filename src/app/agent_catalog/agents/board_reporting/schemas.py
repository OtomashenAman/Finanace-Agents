from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    choice_field,
    money_field,
    percent_setting,
    signed_money_field,
    text_field,
    textarea_field,
)


class BoardReportingInput(AgentInput):
    report_name: str = text_field("Report name", max_length=200)
    reporting_period: str = text_field("Reporting period", max_length=20, help="e.g. 2026-Q3")
    reported_revenue: Decimal = money_field("Reported revenue")
    prior_period_revenue: Decimal = money_field("Prior period revenue")
    operating_profit: Decimal = signed_money_field("Operating profit")
    source_dataset_id: str | None = text_field(
        "Source dataset / approval ID",
        required=False,
        max_length=200,
        help="Where the approved metrics come from (e.g. close package or sign-off ID)",
    )
    known_disclosures: str | None = textarea_field("Known disclosures and reporting notes")


class BoardReportingPolicy(PolicySettings):
    """Board Reporting thresholds (defaults = policy board_reporting/v1)."""

    revenue_change_review_pct: Decimal | None = percent_setting(
        "Revenue change review threshold",
        Decimal("25"),
        help="Revenue moving more than this vs the prior period needs a confirmed explanation",
    )


class BoardPrefillParams(AgentInput):
    """Which period to take from the preparer's monthly profit and loss."""

    reporting_period: str = choice_field(
        "Reporting period",
        help="A month, quarter or year: compared with the same period last year",
    )
