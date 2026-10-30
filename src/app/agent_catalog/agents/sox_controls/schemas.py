from decimal import Decimal

from pydantic import Field

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    choice_field,
    money_field,
    number_field,
    number_setting,
    text_field,
    textarea_field,
)

MAX_COUNT = 1_000_000_000  # fits the INTEGER columns


class SoxControlsInput(AgentInput):
    control_id: str = text_field("Control ID", max_length=100)
    control_owner: str = text_field("Control owner", max_length=200)
    test_period: str | None = text_field(
        "Test period",
        required=False,
        max_length=20,
        help="A month, quarter or year, e.g. 2026-Q3: the population is taken from it",
    )
    population_threshold: Decimal | None = money_field(
        "Population threshold",
        required=False,
        help="Supplier payments of at least this amount are in scope (empty: all)",
    )
    population_count: int = number_field("Population count", ge=1, le=MAX_COUNT)
    items_tested: int = number_field("Items tested", ge=1, le=MAX_COUNT)
    exceptions_found: int = number_field("Exceptions found", le=MAX_COUNT)
    evidence_references: str | None = textarea_field(
        "Evidence references / URLs", help="Where each tested item's evidence is kept"
    )
    test_procedure: str | None = textarea_field("Test procedure / expected control")


class SoxPrefillParams(AgentInput):
    """Which supplier payments make up the tested population."""

    test_period: str = choice_field("Test period", help="A month, quarter or year")
    population_threshold: Decimal = Field(
        Decimal("0"),
        ge=0,
        max_digits=18,
        decimal_places=2,
        title="Payments of at least",
        json_schema_extra={"ui": "money"},
    )


class SoxControlsPolicy(PolicySettings):
    """SOX testing thresholds (defaults = policy sox_controls/v1)."""

    minimum_sample_size: int | None = number_setting(
        "Minimum sample size",
        25,
        help="Fewer items tested (unless the whole population) is flagged. Empty: no minimum",
    )
    tolerable_exceptions: int | None = number_setting(
        "Tolerable exceptions",
        0,
        help="More exceptions than this mean a potential control deficiency",
    )
