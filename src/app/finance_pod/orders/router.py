import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Form, Query, Response, UploadFile

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.orders import service
from src.app.finance_pod.orders.models import PoStatus
from src.app.finance_pod.orders.schemas import PoOut, PoSummary, PoUpdate, ReasonIn, VersionIn
from src.app.finance_pod.requests.exceptions import RequestInvalidError

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 503)
}


@router.get("/purchase-orders", response_model=list[PoSummary])
async def list_pos(
    session: SessionDep,
    _: FinanceAccessDep,
    status_filter: Annotated[PoStatus | None, Query(alias="status")] = None,
) -> list[PoSummary]:
    return await service.summaries(session, status_filter)


@router.get("/requests/{request_id}/po", response_model=PoOut | None, responses=_ERRORS)
async def request_po(
    request_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> PoOut | None:
    """The request's PO (the live one, else the latest cancelled), or null."""
    po = await service.for_request(session, request_id)
    return await service.out(session, po, access.user) if po else None


@router.post("/requests/{request_id}/po", response_model=PoOut, status_code=201, responses=_ERRORS)
async def draft_po(
    request_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> PoOut:
    """The PO agent drafts the PO from the approved request and the chosen vendor (1.6.1)."""
    po = await service.draft(session, access, request_id, ctx)
    return await service.out(session, po, access.user)


@router.get("/purchase-orders/{po_id}", response_model=PoOut, responses=_ERRORS)
async def get_po(po_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep) -> PoOut:
    return await service.out(session, await service.get(session, po_id), access.user)


@router.put("/purchase-orders/{po_id}", response_model=PoOut, responses=_ERRORS)
async def update_po(
    po_id: uuid.UUID,
    body: PoUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> PoOut:
    po = await service.update(session, access, po_id, body, ctx)
    return await service.out(session, po, access.user)


@router.post("/purchase-orders/{po_id}/confirm", response_model=PoOut, responses=_ERRORS)
async def confirm_po(
    po_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> PoOut:
    """The buyer confirms the draft; above the limit it waits for approval."""
    po = await service.confirm(session, access, po_id, body.expected_version, ctx)
    return await service.out(session, po, access.user)


@router.post("/purchase-orders/{po_id}/approve", response_model=PoOut, responses=_ERRORS)
async def approve_po(
    po_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> PoOut:
    """Approval of a PO above the buyer's limit (1.6.2.a)."""
    po = await service.approve(session, access, po_id, body.expected_version, ctx)
    return await service.out(session, po, access.user)


@router.post("/purchase-orders/{po_id}/issue", response_model=PoOut, responses=_ERRORS)
async def issue_po(
    po_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> PoOut:
    """Create it in the ERP and send it to the vendor."""
    po = await service.issue(session, access, po_id, body.expected_version, ctx)
    return await service.out(session, po, access.user)


@router.post("/purchase-orders/{po_id}/acknowledge", response_model=PoOut, responses=_ERRORS)
async def acknowledge_po(
    po_id: uuid.UUID,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    expected_version: Annotated[int, Form()],
    note: Annotated[str, Form(max_length=2000)] = "",
    received_on: Annotated[date | None, Form()] = None,
    file: UploadFile | None = None,
) -> PoOut:
    """Log the vendor's acknowledgement (their reply, optionally as a file)."""
    upload = None
    if file is not None:
        limit = get_settings().upload_max_bytes
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise RequestInvalidError(f"Files can be at most {limit // (1024 * 1024)} MB.")
        upload = (
            (file.filename or "acknowledgement")[:255],
            file.content_type or "application/octet-stream",
            data,
        )
    po = await service.acknowledge(
        session, access, po_id, expected_version, note, received_on, upload, ctx
    )
    return await service.out(session, po, access.user)


@router.get("/purchase-orders/{po_id}/acknowledgement", responses=_ERRORS)
async def acknowledgement_file(
    po_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> Response:
    filename, content_type, content = await service.acknowledgement_file(session, po_id)
    return Response(
        content,
        media_type=content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename.replace(chr(34), "")}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/purchase-orders/{po_id}/cancel", response_model=PoOut, responses=_ERRORS)
async def cancel_po(
    po_id: uuid.UUID,
    body: ReasonIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> PoOut:
    po = await service.cancel(session, access, po_id, body.expected_version, body.reason, ctx)
    return await service.out(session, po, access.user)
