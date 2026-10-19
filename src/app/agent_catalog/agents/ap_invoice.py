from src.app.agent_catalog.agents.base import BaseAgent


class ApInvoiceAgent(BaseAgent):
    key = "ap_invoice"
    code = "01"
    name = "AP Invoice Intake, Coding & Approval"
    short_name = "AP Invoice"
    description = (
        "Extract invoice details, compare PO and receipt, assign GL and flag "
        "duplicate/tax/policy exceptions."
    )
    primary_user = "AP Analyst"
    reviewer = "AP Approver"
