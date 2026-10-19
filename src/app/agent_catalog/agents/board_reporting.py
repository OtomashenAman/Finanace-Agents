from src.app.agent_catalog.agents.base import BaseAgent


class BoardReportingAgent(BaseAgent):
    key = "board_reporting"
    code = "12"
    name = "Financial Reporting, Disclosure & Board Pack"
    short_name = "Board Reporting"
    description = "Generate grounded disclosure and board commentary from approved metrics."
    primary_user = "Reporting Analyst"
    reviewer = "CFO / Controller"
