import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.flows.reporting import packs, views
from src.app.service_pod.flows.reporting.schemas import PackOut, ReportMonths

router = APIRouter(prefix="/reporting", tags=["service pod: financial reporting"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}


@router.get("/months", response_model=ReportMonths)
async def reporting_months(session: SessionDep, _: PodAccessDep) -> ReportMonths:
    """Sources that can make a pack, the months each covers (closed or not), and the cases."""
    return await views.report_months(session)


@router.get("/cases/{case_id}/packs", response_model=list[PackOut], responses=_ERRORS)
async def reporting_packs(
    case_id: uuid.UUID, session: SessionDep, _: PodAccessDep
) -> list[PackOut]:
    return await packs.list_packs(session, case_id)


@router.post("/cases/{case_id}/packs", response_model=PackOut, responses=_ERRORS)
async def reporting_export_pack(
    case_id: uuid.UUID, session: SessionDep, access: PodAccessDep, ctx: RequestContextDep
) -> PackOut:
    """Make the PDF pack from the signed-off content (once per content) and store it."""
    return await packs.export_pack(session, access, case_id, ctx)


@router.get("/cases/{case_id}/packs/{pack_id}.pdf", responses=_ERRORS)
async def reporting_pack_pdf(
    case_id: uuid.UUID, pack_id: uuid.UUID, session: SessionDep, _: PodAccessDep
) -> Response:
    """The stored PDF, after its bytes are checked against the recorded hash."""
    filename, data = await packs.read_pack(session, case_id, pack_id)
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
