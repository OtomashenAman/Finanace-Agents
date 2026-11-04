from typing import Any

from fastapi import APIRouter, Response, UploadFile

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.reference import service, workbook
from src.app.finance_pod.reference.schemas import ImportResult, ReferenceOut
from src.app.finance_pod.reference.workbook import ReferenceInvalidError

router = APIRouter(prefix="/reference")

_ERRORS: dict[int | str, dict[str, Any]] = {422: {"model": ErrorResponse}}


@router.get("", response_model=ReferenceOut)
async def get_reference(session: SessionDep, _: FinanceAccessDep) -> ReferenceOut:
    """Everything the agents work from: cost centres to the authority matrix."""
    return await service.get_reference(session)


@router.get("/template")
async def download_template(_: FinanceAccessDep) -> Response:
    """The workbook with every sheet, its headers and an example row to replace."""
    data, content_type = workbook.template()
    return Response(
        data,
        media_type=content_type,
        headers={"Content-Disposition": 'attachment; filename="finance-pod-reference.xlsx"'},
    )


@router.post("/workbook", response_model=ImportResult, responses=_ERRORS)
async def import_workbook(
    file: UploadFile, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> ImportResult:
    """Load any of the sheets; rows are matched on their code. All or nothing."""
    settings = get_settings()
    data = await file.read(settings.upload_max_bytes + 1)
    if len(data) > settings.upload_max_bytes:
        raise ReferenceInvalidError(
            f"Files can be at most {settings.upload_max_bytes // (1024 * 1024)} MB."
        )
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise ReferenceInvalidError("Upload the reference data as an .xlsx workbook.")
    return await service.import_workbook(session, data, settings.upload_max_rows, access.user, ctx)
