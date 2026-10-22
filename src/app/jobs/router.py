import uuid

from fastapi import APIRouter

from src.app.auth.dependencies import AdminUser
from src.app.common.context import RequestContextDep
from src.app.core.db import SessionDep
from src.app.jobs import service
from src.app.jobs.schemas import JobOut, QueueSummary

router = APIRouter(prefix="/admin/jobs", tags=["background jobs"])


@router.get("", response_model=QueueSummary)
async def summary(session: SessionDep, _: AdminUser) -> QueueSummary:
    """Queue health: counts, the longest wait, jobs retrying and jobs that gave up."""
    return await service.summary(session)


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry(
    job_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, admin: AdminUser
) -> JobOut:
    """Run a failed job again (3 more attempts)."""
    return await service.retry(session, job_id, admin, ctx)
