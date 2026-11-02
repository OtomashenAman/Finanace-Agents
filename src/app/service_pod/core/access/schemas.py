from pydantic import BaseModel

from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import PodKey, WorkflowKey


class WorkflowOut(BaseModel):
    key: WorkflowKey
    pod: PodKey
    name: str
    prefix: str
    description: str
    required: list[Collection]
    signoff_as: str
    signoffs: list[str]  # in order, e.g. Controller then CFO
