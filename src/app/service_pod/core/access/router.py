from typing import Any

from fastapi import APIRouter, Depends

from src.app.service_pod.core.access import service
from src.app.service_pod.core.access.schemas import WorkflowOut
from src.app.service_pod.core.access.service import PodAccess, get_pod_access


def build_router(access_dependency: Any, tag: str) -> APIRouter:
    router = APIRouter(tags=[tag])

    @router.get("/workflows", response_model=list[WorkflowOut])
    async def list_workflows(
        access: PodAccess = Depends(access_dependency),
    ) -> list[WorkflowOut]:
        """The POD's workflows (Service POD: Finance Admin only)."""
        return service.workflows_for(access.pod)

    return router


router = build_router(get_pod_access, "service pod: access")
