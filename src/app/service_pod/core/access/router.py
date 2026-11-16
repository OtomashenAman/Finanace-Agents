from fastapi import APIRouter

from src.app.service_pod.core.access import service
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.access.service import PodAccessDep

router = APIRouter(tags=["service pod: access"])


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(access: PodAccessDep) -> list[WorkflowOut]:
    """The workflows this person works in (all five for a Finance Admin)."""
    return service.workflows_for(access)
