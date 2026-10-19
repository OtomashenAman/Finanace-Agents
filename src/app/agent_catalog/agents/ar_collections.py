from src.app.agent_catalog.agents.base import BaseAgent


class ArCollectionsAgent(BaseAgent):
    key = "ar_collections"
    code = "03"
    name = "AR Collections Prioritization & Dunning"
    short_name = "AR Collections"
    description = "Score aged receivables and draft an appropriate collector communication."
    primary_user = "AR Collector"
    reviewer = "Collections Lead"
