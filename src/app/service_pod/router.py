from fastapi import APIRouter

import src.app.service_pod.flows  # noqa: F401 - registers every workflow (and its router)
from src.app.service_pod.core.access.router import router as access_router
from src.app.service_pod.core.cases.router import router as cases_router
from src.app.service_pod.core.dashboard.router import router as dashboard_router
from src.app.service_pod.core.messaging.router import router as messaging_router
from src.app.service_pod.core.registry import ROUTERS
from src.app.service_pod.core.snapshots.router import router as snapshots_router
from src.app.service_pod.core.tasks.router import router as tasks_router

router = APIRouter(prefix="/pod")
router.include_router(access_router)
router.include_router(snapshots_router)
router.include_router(cases_router)
router.include_router(dashboard_router)
router.include_router(messaging_router)
router.include_router(tasks_router)
for workflow_router in ROUTERS:
    router.include_router(workflow_router)
