from typing import Annotated

from fastapi import APIRouter, Query

from src.app.auth.dependencies import CurrentUser
from src.app.common.clock import utcnow
from src.app.core.db import SessionDep
from src.app.overview import service
from src.app.overview.schemas import OverviewSummary

router = APIRouter(prefix="/overview", tags=["overview"])

Period = Annotated[
    str | None,
    Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, defaults to this month"),
]


@router.get("/summary", response_model=OverviewSummary)
async def get_summary(
    session: SessionDep, user: CurrentUser, period: Period = None
) -> OverviewSummary:
    return await service.get_summary(session, user, period or utcnow().strftime("%Y-%m"))
