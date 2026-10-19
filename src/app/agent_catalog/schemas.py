from pydantic import BaseModel

from src.app.agent_catalog.models import AgentCapacity


class AgentOut(BaseModel):
    key: str
    code: str
    name: str
    short_name: str
    description: str
    primary_user: str
    reviewer: str
    is_active: bool
    has_workspace: bool  # input/result/review screens implemented
    # What the current user may do with this agent (empty for Finance Admin oversight)
    my_capacities: list[AgentCapacity]


class AgentUpdate(BaseModel):
    is_active: bool
