from typing import Annotated

from fastapi import APIRouter, Query

from src.app.auth.dependencies import AdminUser
from src.app.core.db import SessionDep
from src.app.monitoring import service
from src.app.monitoring.schemas import LlmSummary

router = APIRouter(prefix="/admin/ai-monitoring", tags=["ai monitoring"])


@router.get("", response_model=LlmSummary)
async def get_summary(
    session: SessionDep, _: AdminUser, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> LlmSummary:
    """AI explanation calls over the last `days` days: volume, failures, tokens, latency
    (Finance Admin only)."""
    return await service.summary(session, days)
