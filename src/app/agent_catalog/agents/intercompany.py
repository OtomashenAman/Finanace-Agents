from src.app.agent_catalog.agents.base import BaseAgent


class IntercompanyAgent(BaseAgent):
    key = "intercompany"
    code = "06"
    name = "Intercompany Matching, Netting & Settlement"
    short_name = "Intercompany"
    description = "Compare entity-to-entity balances and propose controlled netting."
    primary_user = "Intercompany Analyst"
    reviewer = "Treasury & Tax Reviewer"
