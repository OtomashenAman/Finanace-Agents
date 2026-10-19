from src.app.agent_catalog.agents.base import BaseAgent


class TreasuryCashAgent(BaseAgent):
    key = "treasury_cash"
    code = "08"
    name = "Treasury Cash Forecasting & Liquidity"
    short_name = "Treasury"
    description = "Forecast end cash and detect shortfalls before funds movement."
    primary_user = "Treasury Analyst"
    reviewer = "Treasury Approver"
