import uuid
from typing import Any

from fastapi import APIRouter

from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.flows.ar_collections import views
from src.app.service_pod.flows.ar_collections.schemas import ArPortfolio

router = APIRouter(prefix="/ar", tags=["service pod: AR collections"])

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (403, 404)}


@router.get("/portfolio", response_model=ArPortfolio, responses=_ERRORS)
async def ar_portfolio(
    session: SessionDep, access: PodAccessDep, snapshot_id: uuid.UUID | None = None
) -> ArPortfolio:
    """Open AR, aging and priority customers of a snapshot (default: the latest with AR)."""
    return await views.ar_portfolio(session, access, snapshot_id)
