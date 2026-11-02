from pydantic import BaseModel

from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import WorkflowKey


class WorkflowOut(BaseModel):
    key: WorkflowKey
    name: str
    prefix: str
    description: str
    required: list[Collection]
    signoff_as: str
