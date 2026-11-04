import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Response, UploadFile
from pydantic import TypeAdapter, ValidationError

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.clients import service
from src.app.finance_pod.clients.models import ClientDocumentKind
from src.app.finance_pod.clients.schemas import (
    ApplicationOut,
    ApplicationSummary,
    ClearIn,
    ClientOut,
    Contact,
    DecisionIn,
    HistoryImport,
    InviteIn,
    MonitorResult,
    PortalView,
    ReasonIn,
    ReviewDecisionIn,
    ReviewOut,
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 502, 503)
}
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]

# Finance Admins (FinanceAccessDep on every route)
router = APIRouter()


@router.get("/client-applications", response_model=list[ApplicationSummary])
async def list_applications(session: SessionDep, _: FinanceAccessDep) -> list[ApplicationSummary]:
    return await service.applications(session)


@router.post(
    "/client-applications", response_model=ApplicationOut, status_code=201, responses=_ERRORS
)
async def invite(
    body: InviteIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> ApplicationOut:
    """Open a client's account application: the agent emails the secure link (1.1.1)."""
    row, token = await service.invite(
        session, access, body.client_name, str(body.client_email), ctx
    )
    return await service.application(session, row.id, access.user, token)


@router.get(
    "/client-applications/{application_id}", response_model=ApplicationOut, responses=_ERRORS
)
async def get_application(
    application_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> ApplicationOut:
    return await service.application(session, application_id, access.user)


@router.post(
    "/client-applications/{application_id}/resend", response_model=ApplicationOut, responses=_ERRORS
)
async def resend(
    application_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> ApplicationOut:
    token = await service.resend(session, access, application_id, ctx)
    return await service.application(session, application_id, access.user, token)


@router.post(
    "/client-applications/{application_id}/request-info",
    response_model=ApplicationOut,
    responses=_ERRORS,
)
async def request_info(
    application_id: uuid.UUID,
    body: ReasonIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> ApplicationOut:
    """Back to the client with what's needed, and a new link (earlier answers are kept)."""
    token = await service.request_info(session, access, application_id, body.reason, ctx)
    return await service.application(session, application_id, access.user, token)


@router.post(
    "/client-applications/{application_id}/recheck",
    response_model=ApplicationOut,
    responses=_ERRORS,
)
async def recheck(
    application_id: uuid.UUID,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: LLMDep,
) -> ApplicationOut:
    await service.recheck(session, access, application_id, llm, ctx)
    return await service.application(session, application_id, access.user)


@router.post(
    "/client-applications/{application_id}/clear", response_model=ApplicationOut, responses=_ERRORS
)
async def clear(
    application_id: uuid.UUID,
    body: ClearIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> ApplicationOut:
    await service.clear(session, access, application_id, body.key, body.note, ctx)
    return await service.application(session, application_id, access.user)


@router.post(
    "/client-applications/{application_id}/decide", response_model=ApplicationOut, responses=_ERRORS
)
async def decide(
    application_id: uuid.UUID,
    body: DecisionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> ApplicationOut:
    """The credit controller approves the terms (1.2.2); the account is created (1.3.1)."""
    await service.decide(session, access, application_id, body, ctx)
    return await service.application(session, application_id, access.user)


@router.post(
    "/client-applications/{application_id}/reject", response_model=ApplicationOut, responses=_ERRORS
)
async def reject(
    application_id: uuid.UUID,
    body: ReasonIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> ApplicationOut:
    await service.reject(session, access, application_id, body.reason, ctx)
    return await service.application(session, application_id, access.user)


@router.get("/client-applications/{application_id}/documents/{document_id}", responses=_ERRORS)
async def download_document(
    application_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> Response:
    filename, content_type, content = await service.document(session, application_id, document_id)
    return Response(
        content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename.replace(chr(34), "")}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/clients", response_model=list[ClientOut])
async def list_clients(session: SessionDep, _: FinanceAccessDep) -> list[ClientOut]:
    return await service.clients(session)


@router.post("/clients/history", response_model=HistoryImport, responses=_ERRORS)
async def import_history(
    file: UploadFile, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> HistoryImport:
    """Billing and payment history per client (CSV/XLSX); the monitor then reviews."""
    data = await file.read(10 * 1024 * 1024)
    return await service.import_history(session, access, data, file.filename or "history.csv", ctx)


@router.post("/clients/monitor", response_model=MonitorResult, responses=_ERRORS)
async def run_monitor(
    session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> MonitorResult:
    """The monitor reviews every account now (1.3.2)."""
    result = await service.run_monitor(session, access.user.id, ctx)
    await session.commit()
    return result


@router.get("/clients/{client_id}", response_model=ClientOut, responses=_ERRORS)
async def get_client(client_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep) -> ClientOut:
    return await service.client(session, client_id)


@router.post("/clients/{client_id}/sync", response_model=ClientOut, responses=_ERRORS)
async def sync(
    client_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> ClientOut:
    """Put the lab system back in line with the ERP for this client."""
    return await service.resync(session, access, client_id, ctx)


@router.get("/credit-reviews", response_model=list[ReviewOut])
async def list_reviews(
    session: SessionDep, _: FinanceAccessDep, open_only: bool = False
) -> list[ReviewOut]:
    return await service.reviews(session, open_only)


@router.post("/credit-reviews/{review_id}/decide", response_model=ReviewOut, responses=_ERRORS)
async def decide_review(
    review_id: uuid.UUID,
    body: ReviewDecisionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> ReviewOut:
    return await service.decide_review(session, access, review_id, body, ctx)


# The client's side: no login, the single-use link's token is the key
portal_router = APIRouter(prefix="/client-portal", tags=["client portal"])
_CONTACTS = TypeAdapter(list[Contact])


def _decimal(value: str, label: str) -> Decimal | None:
    if not value.strip():
        return None
    try:
        n = Decimal(value.replace(",", "").strip())
    except InvalidOperation:
        raise service.ClientInvalidError(f"{label}: give a number.") from None
    if n < 0 or n >= Decimal("1e15"):
        raise service.ClientInvalidError(f"{label}: give a number.")
    return n.quantize(Decimal("0.01"))


@portal_router.get("/{token}", response_model=PortalView, responses=_ERRORS)
async def portal_view(token: str, session: SessionDep) -> PortalView:
    return await service.portal_view(session, token)


@portal_router.post("/{token}", status_code=204, responses=_ERRORS)
async def portal_submit(
    token: str,
    session: SessionDep,
    ctx: RequestContextDep,
    llm: LLMDep,
    legal_name: Annotated[str, Form(min_length=1, max_length=200)],
    tax_id: Annotated[str, Form(min_length=1, max_length=40)],
    address: Annotated[str, Form(min_length=5, max_length=2000)],
    billing_email: Annotated[str, Form(min_length=3, max_length=320)],
    contacts: Annotated[str, Form(max_length=20000)],
    currency: Annotated[str, Form(pattern=r"^[A-Z]{3}$")] = "USD",
    country: Annotated[str, Form(pattern=r"^[A-Z]{2}$")] = "US",
    phone: Annotated[str, Form(max_length=40)] = "",
    website: Annotated[str, Form(max_length=200)] = "",
    requested_limit: Annotated[str, Form(max_length=30)] = "",
    requested_terms: Annotated[str, Form(max_length=40)] = "",
    expected_monthly: Annotated[str, Form(max_length=30)] = "",
    years_trading: Annotated[str, Form(max_length=4)] = "",
    registration_file: UploadFile | None = None,
    tax_file: UploadFile | None = None,
    credit_report_file: UploadFile | None = None,
    trade_reference_files: list[UploadFile] | None = None,
) -> Response:
    """The client's application and documents (1.1.1)."""
    try:
        people = [c.model_dump() for c in _CONTACTS.validate_json(contacts)]
        Contact(name="billing", email=billing_email)  # an email address
    except ValidationError:
        raise service.ClientInvalidError("Check the contacts' names and email addresses.") from None
    if not years_trading.strip():
        years = None
    elif years_trading.strip().isdigit():
        years = int(years_trading)
    else:
        raise service.ClientInvalidError("Years trading: give a whole number.")
    fields = {
        "legal_name": legal_name.strip(),
        "tax_id": tax_id.strip(),
        "country": country,
        "address": address.strip(),
        "phone": phone.strip() or None,
        "website": website.strip() or None,
        "billing_email": billing_email.strip().lower(),
        "contacts": people[:10],
        "currency": currency,
        "requested_limit": _decimal(requested_limit, "Credit limit requested"),
        "requested_terms": requested_terms.strip() or None,
        "expected_monthly": _decimal(expected_monthly, "Expected monthly spend"),
        "years_trading": years,
    }
    limit = service.MAX_DOC_BYTES
    uploads: list[tuple[ClientDocumentKind, UploadFile | None]] = [
        (ClientDocumentKind.REGISTRATION, registration_file),
        (ClientDocumentKind.TAX, tax_file),
        (ClientDocumentKind.CREDIT_REPORT, credit_report_file),
        *[(ClientDocumentKind.TRADE_REFERENCE, f) for f in (trade_reference_files or [])[:3]],
    ]
    files = []
    for kind, upload in uploads:
        if upload is None or not upload.filename:
            continue
        data = await upload.read(limit + 1)
        files.append((kind, upload.filename, upload.content_type or "application/pdf", data))
    await service.portal_submit(session, token, fields, files, llm, ctx)
    return Response(status_code=204)
