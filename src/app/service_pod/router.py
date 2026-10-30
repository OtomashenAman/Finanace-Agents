from fastapi import APIRouter

from src.app.service_pod.access.router import router as access_router
from src.app.service_pod.cases.router import router as cases_router
from src.app.service_pod.messaging.router import router as messaging_router
from src.app.service_pod.snapshots.router import router as snapshots_router
from src.app.service_pod.tasks.router import router as tasks_router

router = APIRouter(prefix="/pod")
router.include_router(access_router)
router.include_router(snapshots_router)
router.include_router(cases_router)
router.include_router(messaging_router)
router.include_router(tasks_router)
