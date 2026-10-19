from src.app.agent_catalog.agents.base import BaseAgent


class SoxControlsAgent(BaseAgent):
    key = "sox_controls"
    code = "11"
    name = "Audit Evidence, Controls Testing & SOX"
    short_name = "SOX Controls"
    description = "Test control evidence and produce a traceable exception workpaper."
    primary_user = "Internal Auditor"
    reviewer = "SOX Reviewer"
