from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    number_field,
    number_setting,
    text_field,
    textarea_field,
)

MAX_COUNT = 1_000_000_000  # fits the INTEGER columns


class SoxControlsInput(AgentInput):
    control_id: str = text_field("Control ID", max_length=100)
    control_owner: str = text_field("Control owner", max_length=200)
    population_count: int = number_field("Population count", ge=1, le=MAX_COUNT)
    items_tested: int = number_field("Items tested", ge=1, le=MAX_COUNT)
    exceptions_found: int = number_field("Exceptions found", le=MAX_COUNT)
    evidence_references: str | None = textarea_field(
        "Evidence references / URLs", help="Where each tested item's evidence is kept"
    )
    test_procedure: str | None = textarea_field("Test procedure / expected control")


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
