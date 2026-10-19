from src.app.agent_catalog.agents.base import BaseAgent


class FinancialCloseAgent(BaseAgent):
    key = "financial_close"
    code = "05"
    name = "Financial Close & Account Reconciliation"
    short_name = "Financial Close"
    description = "Reconcile GL to subledger and draft an exception explanation or journal."
    primary_user = "Controller"
    reviewer = "Controller"
