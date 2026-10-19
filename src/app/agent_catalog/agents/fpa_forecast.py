from src.app.agent_catalog.agents.base import BaseAgent


class FpaForecastAgent(BaseAgent):
    key = "fpa_forecast"
    code = "07"
    name = "FP&A Forecast, Variance & Scenario Planning"
    short_name = "FP&A"
    description = "Evaluate actual/budget differences and parameterized scenarios."
    primary_user = "FP&A Analyst"
    reviewer = "FP&A Manager"
