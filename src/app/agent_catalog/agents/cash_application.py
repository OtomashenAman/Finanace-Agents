from src.app.agent_catalog.agents.base import BaseAgent


class CashApplicationAgent(BaseAgent):
    key = "cash_application"
    code = "04"
    name = "Cash Application & Deductions Resolution"
    short_name = "Cash Application"
    description = "Match bank remittances to open invoices and identify deductions."
    primary_user = "Cash Analyst"
    reviewer = "Cash Application Reviewer"
