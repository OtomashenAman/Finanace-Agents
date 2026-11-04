import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, UploadFile

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.invoices import service
from src.app.finance_pod.invoices.models import ExceptionStatus, InvoiceStatus
from src.app.finance_pod.invoices.schemas import (
    CreditNoteIn,
    DecisionIn,
    DeleteIn,
    ExceptionOut,
    InvoiceIn,
    InvoiceOut,
    InvoiceSummary,
    InvoiceUpdate,
    NoteIn,
    ReceiptIn,
    ReceiptOut,
    ReceiptPortalView,
    ReceiptRequestOut,
    VersionIn,
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 503)
}
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]

# Finance Admins (FinanceAccessDep on every route)
router = APIRouter()


@router.get("/invoices", response_model=list[InvoiceSummary])
async def list_invoices(
    session: SessionDep,
    _: FinanceAccessDep,
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    po_id: uuid.UUID | None = None,
) -> list[InvoiceSummary]:
    """Newest first; optionally only one status, or only one PO's invoices."""
    return await service.list_invoices(session, status_filter, po_id)


@router.post("/invoices/capture", response_model=InvoiceOut, status_code=201, responses=_ERRORS)
async def capture(
    file: UploadFile,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: LLMDep,
) -> InvoiceOut:
    """Upload an invoice: the capture agent reads it (3.1). AP then confirms the data."""
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise service.InvoiceInvalidError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    inv = await service.capture(
        session, access, file.filename or "invoice", file.content_type or "", data, llm, ctx
    )
    return await service.detail(session, inv.id)


@router.post("/invoices", response_model=InvoiceOut, status_code=201, responses=_ERRORS)
async def create_manual(
    body: InvoiceIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> InvoiceOut:
    inv = await service.create_manual(session, access, body, ctx)
    return await service.detail(session, inv.id)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, responses=_ERRORS)
async def get_invoice(
    invoice_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> InvoiceOut:
    return await service.detail(session, invoice_id)


@router.put("/invoices/{invoice_id}", response_model=InvoiceOut, responses=_ERRORS)
async def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    await service.update(session, access, invoice_id, body, body.expected_version, ctx)
    return await service.detail(session, invoice_id)


@router.post("/invoices/{invoice_id}/post", response_model=InvoiceOut, responses=_ERRORS)
async def post_invoice(
    invoice_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    """Confirm the data: duplicate guard, ERP posting, then the match (3.2, 3.4)."""
    await service.validate_and_post(session, access, invoice_id, body.expected_version, ctx)
    return await service.detail(session, invoice_id)


@router.post("/invoices/{invoice_id}/not-duplicate", response_model=InvoiceOut, responses=_ERRORS)
async def override_duplicate(
    invoice_id: uuid.UUID,
    body: NoteIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    """A person confirms it isn't a duplicate (with why): it's posted and matched."""
    await service.validate_and_post(
        session, access, invoice_id, body.expected_version, ctx, override_note=body.note
    )
    return await service.detail(session, invoice_id)


@router.post("/invoices/{invoice_id}/explain", response_model=InvoiceOut, responses=_ERRORS)
async def explain(
    invoice_id: uuid.UUID,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: LLMDep,
) -> InvoiceOut:
    """The match agent explains its match in plain words (citing computed figures only)."""
    await service.explain_match(session, access, invoice_id, llm, ctx)
    return await service.detail(session, invoice_id)


@router.post("/invoices/{invoice_id}/rematch", response_model=InvoiceOut, responses=_ERRORS)
async def rematch(
    invoice_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> InvoiceOut:
    await service.rematch(session, access, invoice_id, ctx)
    return await service.detail(session, invoice_id)


@router.post("/invoices/{invoice_id}/reject", response_model=InvoiceOut, responses=_ERRORS)
async def reject(
    invoice_id: uuid.UUID,
    body: NoteIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    await service.reject(session, access, invoice_id, body.note, ctx)
    return await service.detail(session, invoice_id)


@router.delete("/invoices/{invoice_id}", status_code=204, responses=_ERRORS)
async def delete_invoice(
    invoice_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> Response:
    """Remove an invoice (and its exception); the audit trail keeps the record."""
    await service.delete_invoices(session, access, [invoice_id], ctx)
    return Response(status_code=204)


@router.post("/invoices/delete", responses=_ERRORS)
async def delete_invoices(
    body: DeleteIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> dict[str, int]:
    """Remove several invoices at once (e.g. to run a demo again)."""
    return {"deleted": await service.delete_invoices(session, access, body.ids, ctx)}


@router.get("/invoices/{invoice_id}/file", responses=_ERRORS)
async def invoice_file(invoice_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep) -> Response:
    filename, content_type, content = await service.file(session, invoice_id)
    return Response(
        content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename.replace(chr(34), "")}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/invoice-exceptions", response_model=list[ExceptionOut])
async def list_exceptions(
    session: SessionDep,
    _: FinanceAccessDep,
    status_filter: Annotated[ExceptionStatus | None, Query(alias="status")] = None,
    open_only: bool = True,
) -> list[ExceptionOut]:
    """Variances being resolved, oldest first (exception ageing)."""
    return await service.list_exceptions(session, status_filter, open_only)


@router.post(
    "/invoice-exceptions/{exception_id}/decide", response_model=InvoiceOut, responses=_ERRORS
)
async def decide(
    exception_id: uuid.UUID,
    body: DecisionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    """The buyer decides: accept, credit note, amend PO or reject (3.5.2)."""
    inv = await service.decide(session, access, exception_id, body, ctx)
    return await service.detail(session, inv.id)


@router.post(
    "/invoice-exceptions/{exception_id}/credit-note", response_model=InvoiceOut, responses=_ERRORS
)
async def credit_note(
    exception_id: uuid.UUID,
    body: CreditNoteIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    inv = await service.credit_note(session, access, exception_id, body.amount, body.reference, ctx)
    return await service.detail(session, inv.id)


@router.get("/purchase-orders/{po_id}/receipts", response_model=list[ReceiptOut])
async def po_receipts(
    po_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> list[ReceiptOut]:
    return await service.receipts(session, po_id)


@router.post(
    "/purchase-orders/{po_id}/receipts",
    response_model=list[ReceiptOut],
    status_code=201,
    responses=_ERRORS,
)
async def record_receipt(
    po_id: uuid.UUID,
    body: ReceiptIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> list[ReceiptOut]:
    """Record what arrived (in the app); invoices waiting on it are matched again."""
    await service.record_receipt(session, access, po_id, body, ctx)
    return await service.receipts(session, po_id)


@router.post(
    "/receipt-requests/{request_id}/nudge", response_model=ReceiptRequestOut, responses=_ERRORS
)
async def nudge(
    request_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> ReceiptRequestOut:
    """The receipt agent asks the receiver again (a new link; the old one stops)."""
    req, token = await service.nudge(session, access, request_id, ctx)
    return service.request_out(req, token)


# The receiver's side: no login, the single-use link is the key (mobile)
receipt_portal_router = APIRouter(prefix="/receipt-confirm", tags=["receipt confirmation"])


@receipt_portal_router.get("/{token}", response_model=ReceiptPortalView, responses=_ERRORS)
async def receipt_view(token: str, session: SessionDep) -> ReceiptPortalView:
    return await service.portal_view(session, token)


@receipt_portal_router.post("/{token}", status_code=204, responses=_ERRORS)
async def receipt_confirm(
    token: str, body: ReceiptIn, session: SessionDep, ctx: RequestContextDep
) -> Response:
    await service.portal_confirm(session, token, body, ctx)
    return Response(status_code=204)
