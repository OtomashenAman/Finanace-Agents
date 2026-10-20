from pydantic import BaseModel

from src.app.agent_catalog.models import AgentCapacity
from src.app.data_sources.records import RecordType


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
    # Data source records that can prefill a run (e.g. "bill"); None: manual input only
    source_record_type: RecordType | None
    # What the current user may do with this agent (Finance Admin: always both)
    my_capacities: list[AgentCapacity]


class AgentUpdate(BaseModel):
    is_active: bool
