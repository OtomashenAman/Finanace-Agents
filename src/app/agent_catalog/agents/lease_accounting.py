from src.app.agent_catalog.agents.base import BaseAgent


class LeaseAccountingAgent(BaseAgent):
    key = "lease_accounting"
    code = "10"
    name = "Lease Accounting & Contract Abstraction"
    short_name = "Lease Accounting"
    description = "Extract lease terms and build a preliminary amortization illustration."
    primary_user = "Lease Accountant"
    reviewer = "Lease Accounting Reviewer"
