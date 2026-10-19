from decimal import Decimal

from src.app.agent_catalog.agents.fields import AgentInput, money_field, text_field


class ApInvoiceInput(AgentInput):
    supplier: str = text_field("Supplier", max_length=200)
    invoice_number: str = text_field("Invoice number", max_length=100)
    legal_entity: str = text_field("Legal entity", max_length=200)
    invoice_total: Decimal = money_field("Invoice total", gt=Decimal(0))
    po_authorized_amount: Decimal = money_field("PO authorized amount")
    received_amount: Decimal = money_field(
        "Received amount", help="Value of goods or services received against the PO"
    )
    tax_total: Decimal | None = money_field("Tax total", required=False)
    proposed_gl_account: str | None = text_field(
        "Proposed GL account", required=False, max_length=50
    )
