from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    money_field,
    number_field,
    text_field,
    textarea_field,
)


class IntercompanyInput(AgentInput):
    sending_entity: str = text_field("Sending entity", max_length=200, help="Holds the AR")
    receiving_entity: str = text_field("Receiving entity", max_length=200, help="Holds the AP")
    currency: str = text_field("Currency", max_length=3, pattern=r"^[A-Za-z]{3}$", help="e.g. USD")
    intercompany_ar: Decimal = money_field("Intercompany AR")
    counterparty_ap: Decimal = money_field("Counterparty AP")
    translation_rate: Decimal = number_field(
        "Translation rate",
        ge=Decimal("0.000001"),
        le=Decimal("1000000"),
        decimal_places=8,
        help="Converts the counterparty AP into the AR currency (1 if both are the same)",
    )
    matching_tolerance: Decimal = money_field("Matching tolerance")
    transfer_pricing_notes: str | None = textarea_field("Transfer-pricing/policy notes")
