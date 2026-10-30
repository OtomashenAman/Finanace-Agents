from decimal import Decimal
from typing import Literal

from pydantic import Field

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    choice_field,
    money_field,
    signed_money_field,
    text_field,
    textarea_field,
)


class FinancialCloseInput(AgentInput):
    gl_account: str = text_field("GL account", max_length=100)
    close_period: str = text_field(
        "Close period", max_length=7, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", help="e.g. 2026-09"
    )
    accounting_basis: Literal["Accrual", "Cash"] | None = Field(
        None,
        title="Accounting basis",
        description="Both balances must be on the same basis",
        json_schema_extra={"ui": "choice", "options": ["Accrual", "Cash"]},
    )
    currency: str | None = text_field(
        "Currency",
        required=False,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
        help="Both balances in this currency, e.g. USD",
    )
    gl_balance: Decimal = signed_money_field("GL balance")
    subledger_balance: Decimal = signed_money_field("Subledger balance")
    materiality_threshold: Decimal = money_field("Materiality threshold")
    known_reconciling_items: Decimal | None = signed_money_field(
        "Known reconciling items",
        required=False,
        help="Net amount of identified items (timing, in-transit) explaining GL minus subledger",
    )
    proposed_adjustment_rationale: str | None = textarea_field("Proposed adjustment rationale")


class FinancialClosePrefillParams(AgentInput):
    """Which account and month to take from the preparer's month-end balances."""

    gl_account: str = choice_field("GL account")
    close_period: str = choice_field("Close period")
