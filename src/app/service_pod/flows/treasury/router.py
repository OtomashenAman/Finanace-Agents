import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.flows.treasury import views
from src.app.service_pod.flows.treasury.schemas import TreasurySources

router = APIRouter(prefix="/treasury", tags=["service pod: treasury forecast"])

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (403, 404)}


@router.get("/sources", response_model=TreasurySources)
async def treasury_sources(session: SessionDep, _: PodAccessDep) -> TreasurySources:
    """Sources with a cash position (and whether it can open a forecast), and the cases."""
    return await views.sources(session)


@router.get("/cases/{case_id}/forecast.csv", responses=_ERRORS)
async def treasury_forecast_csv(
    case_id: uuid.UUID, session: SessionDep, _: PodAccessDep
) -> Response:
    filename, text = await views.forecast_csv(session, case_id)
    return Response(
        text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
