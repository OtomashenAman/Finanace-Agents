from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    bool_field,
    money_field,
    money_setting,
    number_field,
    number_setting,
    text_field,
    textarea_field,
)


class ArCollectionsInput(AgentInput):
    customer: str = text_field("Customer", max_length=200)
    open_balance: Decimal = money_field("Open balance", gt=Decimal(0))
    days_overdue: int = number_field("Days overdue", le=3650, help="0 if not yet due")
    previous_late_payments: int = number_field("Previous late payments", le=1000)
    open_dispute: bool = bool_field("Open dispute")
    strategic_account: bool = bool_field("Strategic account")
    promise_to_pay: str | None = text_field(
        "Promise to pay date / details", required=False, max_length=500
    )
    collection_notes: str | None = textarea_field("Collection notes")


class ArCollectionsPolicy(PolicySettings):
    """AR collections thresholds (defaults = policy ar_collections/v1)."""

    high_exposure_amount: Decimal | None = money_setting(
        "High exposure above",
        Decimal("50000.00"),
        help="Open balances above this add to the priority score. Empty: no exposure points",
    )
    reminder_score: int = number_setting(
        "Reminder from score", 30, help="Priority score from which a reminder is proposed"
    )
    escalate_score: int = number_setting(
        "Escalate from score", 60, help="Priority score from which escalation is proposed"
    )
