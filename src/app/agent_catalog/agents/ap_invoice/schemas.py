from decimal import Decimal

from src.app.agent_catalog.agents.fields import (
    AgentInput,
    PolicySettings,
    money_field,
    money_setting,
    text_field,
)


class ApInvoiceInput(AgentInput):
    supplier: str = text_field("Supplier", max_length=200)
    invoice_number: str = text_field("Invoice number", max_length=100)
    invoice_total: Decimal = money_field("Invoice total", gt=Decimal(0))
    po_authorized_amount: Decimal = money_field("PO authorized amount")
    received_amount: Decimal = money_field(
        "Received amount", help="Value of goods or services received against the PO"
    )
    tax_total: Decimal | None = money_field("Tax total", required=False)
    proposed_gl_account: str | None = text_field(
        "Proposed GL account", required=False, max_length=50
    )


class ApInvoicePolicy(PolicySettings):
    """AP Invoice thresholds (defaults = policy ap_invoice/v1)."""

    po_tolerance: Decimal = money_setting(
        "PO match tolerance",
        Decimal("0.00"),
        help="Largest invoice vs PO difference still treated as a match",
    )
    receipt_tolerance: Decimal = money_setting(
        "Receipt match tolerance",
        Decimal("0.00"),
        help="Largest invoice vs received difference still treated as a match",
    )
    high_value_amount: Decimal | None = money_setting(
        "High-value invoice limit",
        None,
        help="Invoices above this are flagged for extra scrutiny. Empty: no limit",
    )
