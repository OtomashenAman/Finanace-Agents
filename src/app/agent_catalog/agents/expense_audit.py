from src.app.agent_catalog.agents.base import BaseAgent


class ExpenseAuditAgent(BaseAgent):
    key = "expense_audit"
    code = "02"
    name = "Expense Audit & Corporate Card Compliance"
    short_name = "Expense Audit"
    description = "Evaluate receipts and card claims for duplicate, policy and anomaly risk."
    primary_user = "Expense Auditor"
    reviewer = "Finance Audit"
