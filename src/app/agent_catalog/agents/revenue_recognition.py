from src.app.agent_catalog.agents.base import BaseAgent


class RevenueRecognitionAgent(BaseAgent):
    key = "revenue_recognition"
    code = "09"
    name = "Revenue Recognition & Contract Accounting"
    short_name = "Revenue Recognition"
    description = "Abstract ASC 606/IFRS 15 facts and draft a schedule for review."
    primary_user = "Revenue Accountant"
    reviewer = "Revenue Controller"
