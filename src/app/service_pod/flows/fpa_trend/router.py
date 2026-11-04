import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.core.cases.schemas import CaseDetail
from src.app.service_pod.core.snapshots.contract import Period
from src.app.service_pod.flows.fpa_trend import narrative, views
from src.app.service_pod.flows.fpa_trend.schemas import FpaPeriods

router = APIRouter(prefix="/fpa", tags=["service pod: fp&a trends"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}
LLM = Annotated[LLMProvider, Depends(get_llm_provider)]


class CommentaryRequest(BaseModel):
    expected_version: int = Field(ge=1)


@router.get("/periods", response_model=FpaPeriods)
async def fpa_periods(session: SessionDep, _: PodAccessDep) -> FpaPeriods:
    """Sources with P&L lines (and the months each covers), and the FP&A cases."""
    return await views.periods(session)


@router.post("/cases/{case_id}/commentary", response_model=CaseDetail, responses=_ERRORS)
async def fpa_commentary(
    case_id: uuid.UUID,
    body: CommentaryRequest,
    session: SessionDep,
    access: PodAccessDep,
    llm: LLM,
) -> CaseDetail:
    """AI drafts a few findings and at most three follow-ups, citing the engine's facts."""
    return await narrative.draft_commentary(session, access, case_id, body.expected_version, llm)


@router.get("/cases/{case_id}/drill", responses=_ERRORS)
async def fpa_drill(
    case_id: uuid.UUID, account_id: str, period: Period, session: SessionDep, _: PodAccessDep
) -> dict[str, Any]:
    """One account in one month: its GL line and transactions, from the case's source."""
    return await views.drill(session, case_id, account_id, period)


@router.get("/cases/{case_id}/evidence.csv", responses=_ERRORS)
async def fpa_evidence(case_id: uuid.UUID, session: SessionDep, _: PodAccessDep) -> Response:
    filename, text = await views.evidence_csv(session, case_id)
    return Response(
        text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/cases/{case_id}/pack.json", responses=_ERRORS)
async def fpa_pack(case_id: uuid.UUID, session: SessionDep, access: PodAccessDep) -> JSONResponse:
    """The pack as the Finance Head signed it off (refused before a valid sign-off)."""
    filename, pack = await views.approved_pack(session, access, case_id)
    return JSONResponse(pack, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
