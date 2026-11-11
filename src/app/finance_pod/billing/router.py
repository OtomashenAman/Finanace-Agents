import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Response, UploadFile

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.billing import service, workbook
from src.app.finance_pod.billing.models import SalesInvoiceStatus, SubmissionStatus
from src.app.finance_pod.billing.schemas import (
    ClearFlagIn,
    FeeScheduleOut,
    ImportResult,
    InvoiceOut,
    InvoiceSummary,
    LabEventIn,
    OverrideDecisionIn,
    OverrideIn,
    PublicInvoiceView,
    ReasonIn,
    ReportIssuedIn,
    StatementOut,
    SubmissionIn,
    SubmissionOut,
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
}


def _file(name: str, content_type: str, data: bytes) -> Response:
    return Response(
        data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# Finance Admins (FinanceAccessDep on every route)
router = APIRouter()


@router.get("/lab-submissions", response_model=list[SubmissionOut])
async def list_submissions(
    session: SessionDep, _: FinanceAccessDep, status: SubmissionStatus | None = None
) -> list[SubmissionOut]:
    return await service.submissions(session, status)


@router.post("/lab-submissions", response_model=SubmissionOut, status_code=201, responses=_ERRORS)
async def create_submission(
    body: SubmissionIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> SubmissionOut:
    """A submission received by the lab (until the lab system sends it by API)."""
    row = await service.create_submission(session, body, ctx, actor_id=access.user.id, via="screen")
    await session.commit()
    return await service.submission(session, row.id)


@router.post("/lab-submissions/import", response_model=ImportResult, responses=_ERRORS)
async def import_submissions(
    file: UploadFile, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> ImportResult:
    """The lab system's export (CSV/XLSX), one row per service."""
    data = await file.read(10 * 1024 * 1024)
    return await service.import_submissions(session, access, data, file.filename or "lab.csv", ctx)


@router.get("/lab-submissions/{submission_id}", response_model=SubmissionOut, responses=_ERRORS)
async def get_submission(
    submission_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> SubmissionOut:
    return await service.submission(session, submission_id)


@router.post(
    "/lab-submissions/{submission_id}/report-issued", response_model=InvoiceOut, responses=_ERRORS
)
async def report_issued(
    submission_id: uuid.UUID,
    body: ReportIssuedIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    """The report is issued: the billing agent builds the invoice (3.1)."""
    inv = await service.issue_report(session, access, submission_id, body.performed, ctx)
    return await service.invoice(session, inv.id)


@router.post(
    "/lab-submissions/{submission_id}/cancel", response_model=SubmissionOut, responses=_ERRORS
)
async def cancel_submission(
    submission_id: uuid.UUID,
    body: ReasonIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> SubmissionOut:
    return await service.cancel_submission(session, access, submission_id, body.reason, ctx)


@router.get("/sales-invoices", response_model=list[InvoiceSummary])
async def list_invoices(
    session: SessionDep, _: FinanceAccessDep, status: SalesInvoiceStatus | None = None
) -> list[InvoiceSummary]:
    return await service.invoices(session, status)


@router.get("/sales-invoices/{invoice_id}", response_model=InvoiceOut, responses=_ERRORS)
async def get_invoice(
    invoice_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> InvoiceOut:
    return await service.invoice(session, invoice_id)


@router.get("/sales-invoices/{invoice_id}/pdf", responses=_ERRORS)
async def invoice_pdf(invoice_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep) -> Response:
    name, data = await service.invoice_pdf(session, invoice_id)
    return _file(name, "application/pdf", data)


@router.post("/sales-invoices/{invoice_id}/override", response_model=InvoiceOut, responses=_ERRORS)
async def propose_override(
    invoice_id: uuid.UUID,
    body: OverrideIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    await service.propose_override(
        session, access, invoice_id, body.line_id, body.price, body.reason, ctx
    )
    return await service.invoice(session, invoice_id)


@router.post(
    "/sales-invoices/{invoice_id}/override/decide", response_model=InvoiceOut, responses=_ERRORS
)
async def decide_override(
    invoice_id: uuid.UUID,
    body: OverrideDecisionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    """The billing analyst approves or rejects a price override (3.3.1.b)."""
    await service.decide_override(
        session, access, invoice_id, body.line_id, body.approve, body.note, ctx
    )
    return await service.invoice(session, invoice_id)


@router.post("/sales-invoices/{invoice_id}/clear", response_model=InvoiceOut, responses=_ERRORS)
async def clear_flag(
    invoice_id: uuid.UUID,
    body: ClearFlagIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    await service.clear_flag(session, access, invoice_id, body.line_id, body.key, body.note, ctx)
    return await service.invoice(session, invoice_id)


@router.post("/sales-invoices/{invoice_id}/approve", response_model=InvoiceOut, responses=_ERRORS)
async def approve(
    invoice_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> InvoiceOut:
    """Release a reviewed invoice: the delivery agent posts and sends it (3.5)."""
    await service.approve(session, access, invoice_id, ctx)
    return await service.invoice(session, invoice_id)


@router.post("/sales-invoices/{invoice_id}/void", response_model=InvoiceOut, responses=_ERRORS)
async def void(
    invoice_id: uuid.UUID,
    body: ReasonIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> InvoiceOut:
    await service.void(session, access, invoice_id, body.reason, ctx)
    return await service.invoice(session, invoice_id)


@router.get("/fee-schedule", response_model=FeeScheduleOut)
async def fee_schedule(session: SessionDep, _: FinanceAccessDep) -> FeeScheduleOut:
    return await service.fee_schedule(session)


@router.get("/fee-schedule/template")
async def fee_template(_: FinanceAccessDep) -> Response:
    data, content_type = workbook.template()
    return _file("fee-schedule.xlsx", content_type, data)


@router.post("/fee-schedule", response_model=FeeScheduleOut, responses=_ERRORS)
async def upload_fee_schedule(
    file: UploadFile, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> FeeScheduleOut:
    """Replace the fee schedule, contract prices and tax rates (all or nothing)."""
    data = await file.read(10 * 1024 * 1024)
    return await service.upload_fee_schedule(session, access, data, ctx)


@router.get("/statements", response_model=list[StatementOut])
async def list_statements(session: SessionDep, _: FinanceAccessDep) -> list[StatementOut]:
    return await service.statements(session)


@router.post("/statements/send", responses=_ERRORS)
async def send_statements(
    session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> dict[str, Any]:
    """Last month's statements now (the delivery agent also sends them on the 1st)."""
    return await service.send_statements(session, access, ctx)


# The lab system's side: no login, the shared lab key (X-Lab-Key) authenticates it
lab_router = APIRouter(prefix="/lab-events", tags=["lab events"])


@lab_router.post("", responses=_ERRORS)
async def lab_event(
    body: LabEventIn,
    session: SessionDep,
    ctx: RequestContextDep,
    x_lab_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """A submission received, or its report issued (which builds the invoice)."""
    return await service.lab_event(
        session, x_lab_key, body.event, body.submission, body.received, body.performed, ctx
    )


# The client's side: no login, the invoice link's token is the key
invoice_link_router = APIRouter(prefix="/client-invoice", tags=["client invoice"])


@invoice_link_router.get("/{token}", response_model=PublicInvoiceView, responses=_ERRORS)
async def public_invoice(token: str, session: SessionDep) -> PublicInvoiceView:
    return await service.public_view(session, token)


@invoice_link_router.get("/{token}/pdf", responses=_ERRORS)
async def public_invoice_pdf(token: str, session: SessionDep) -> Response:
    name, data = await service.public_pdf(session, token)
    return _file(name, "application/pdf", data)
