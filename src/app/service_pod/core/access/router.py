from fastapi import APIRouter

from src.app.service_pod.core.access import service
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.access.service import PodAccessDep

router = APIRouter(tags=["service pod: access"])


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(_: PodAccessDep) -> list[WorkflowOut]:
    """The five workflows (Finance Admin only, like the whole Service POD)."""
    return service.workflows_for()
