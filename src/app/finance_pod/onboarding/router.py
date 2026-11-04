import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Response, UploadFile

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.onboarding import sanctions, service
from src.app.finance_pod.onboarding.models import DocumentKind
from src.app.finance_pod.onboarding.schemas import (
    BankChangeIn,
    CallbackIn,
    ClearIn,
    InviteIn,
    OnboardingOut,
    OnboardingSummary,
    PortalView,
    RejectIn,
    SanctionsInfo,
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 502, 503)
}
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]

# Finance Admins (FinanceAccessDep on every route)
router = APIRouter(prefix="/onboardings")


@router.get("", response_model=list[OnboardingSummary])
async def list_onboardings(session: SessionDep, _: FinanceAccessDep) -> list[OnboardingSummary]:
    return await service.summaries(session)


@router.post("", response_model=OnboardingOut, status_code=201, responses=_ERRORS)
async def invite(
    body: InviteIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> OnboardingOut:
    """Onboard a new vendor: the agent sends the secure portal link (1.5.1.a)."""
    row, token = await service.invite(
        session,
        access,
        vendor_name=body.vendor_name,
        vendor_email=str(body.vendor_email),
        request_id=body.request_id,
        ctx=ctx,
    )
    await session.commit()
    return await service.detail(session, row.id, access.user, token)


@router.post("/bank-change", response_model=OnboardingOut, status_code=201, responses=_ERRORS)
async def bank_change(
    body: BankChangeIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> OnboardingOut:
    """A vendor's new bank details: only via the portal, with the same checks."""
    row, token = await service.bank_change(
        session,
        access,
        body.vendor_code,
        str(body.vendor_email) if body.vendor_email else None,
        ctx,
    )
    return await service.detail(session, row.id, access.user, token)


@router.get("/sanctions", response_model=SanctionsInfo)
async def sanctions_info(session: SessionDep, _: FinanceAccessDep) -> SanctionsInfo:
    info = await sanctions.info(session)
    return SanctionsInfo(
        entries=info.entries, loaded_at=info.loaded_at, source_url=get_settings().ofac_sdn_url
    )


@router.post("/sanctions/refresh", response_model=SanctionsInfo, responses=_ERRORS)
async def refresh_sanctions(
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    file: UploadFile | None = None,
) -> SanctionsInfo:
    """Load OFAC's current SDN list (downloaded), or an uploaded sdn.csv."""
    from src.app.audit.service import record_event

    data = await file.read(50 * 1024 * 1024) if file is not None else None
    count = await sanctions.load(session, data)
    record_event(
        session,
        "fpod.sanctions_loaded",
        ctx,
        actor_id=access.user.id,
        entries=count,
        summary=f"Loaded the OFAC SDN sanctions list ({count:,} entries"
        + (", uploaded)" if data else ", downloaded)"),
    )
    await session.commit()
    return await sanctions_info(session, access)


@router.get("/{onboarding_id}", response_model=OnboardingOut, responses=_ERRORS)
async def get_onboarding(
    onboarding_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> OnboardingOut:
    return await service.detail(session, onboarding_id, access.user)


@router.post("/{onboarding_id}/resend", response_model=OnboardingOut, responses=_ERRORS)
async def resend(
    onboarding_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> OnboardingOut:
    token = await service.resend(session, access, onboarding_id, ctx)
    return await service.detail(session, onboarding_id, access.user, token)


@router.post("/{onboarding_id}/resubmission", response_model=OnboardingOut, responses=_ERRORS)
async def request_resubmission(
    onboarding_id: uuid.UUID,
    body: RejectIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> OnboardingOut:
    """Send the vendor a new link to fill the form again (what they sent is discarded)."""
    token = await service.request_resubmission(session, access, onboarding_id, body.reason, ctx)
    return await service.detail(session, onboarding_id, access.user, token)


@router.post("/{onboarding_id}/recheck", response_model=OnboardingOut, responses=_ERRORS)
async def recheck(
    onboarding_id: uuid.UUID,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> OnboardingOut:
    await service.rerun_agent(session, access, onboarding_id, llm, ctx)
    return await service.detail(session, onboarding_id, access.user)


@router.post("/{onboarding_id}/clear", response_model=OnboardingOut, responses=_ERRORS)
async def clear(
    onboarding_id: uuid.UUID,
    body: ClearIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> OnboardingOut:
    await service.clear(session, access, onboarding_id, body.key, body.note, ctx)
    return await service.detail(session, onboarding_id, access.user)


@router.post("/{onboarding_id}/verify", response_model=OnboardingOut, responses=_ERRORS)
async def verify(
    onboarding_id: uuid.UUID,
    body: CallbackIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> OnboardingOut:
    """The AP analyst's call-back confirmed the bank details (1.5.2.a)."""
    await service.verify(session, access, onboarding_id, body, ctx)
    return await service.detail(session, onboarding_id, access.user)


@router.post("/{onboarding_id}/activate", response_model=OnboardingOut, responses=_ERRORS)
async def activate(
    onboarding_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> OnboardingOut:
    """The second approver activates the vendor (1.5.2.b)."""
    await service.activate(session, access, onboarding_id, ctx)
    return await service.detail(session, onboarding_id, access.user)


@router.post("/{onboarding_id}/reject", response_model=OnboardingOut, responses=_ERRORS)
async def reject(
    onboarding_id: uuid.UUID,
    body: RejectIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> OnboardingOut:
    await service.reject(session, access, onboarding_id, body.reason, ctx)
    return await service.detail(session, onboarding_id, access.user)


@router.get("/{onboarding_id}/documents/{document_id}", responses=_ERRORS)
async def download_document(
    onboarding_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> Response:
    filename, content_type, content = await service.document(session, onboarding_id, document_id)
    return Response(
        content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename.replace(chr(34), "")}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


# The vendor's side: no login, the single-use link's token is the key
portal_router = APIRouter(prefix="/vendor-portal", tags=["vendor portal"])


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
    tax_form: Annotated[str, Form(max_length=10)],
    address: Annotated[str, Form(min_length=5, max_length=2000)],
    bank_name: Annotated[str, Form(min_length=1, max_length=200)],
    account_name: Annotated[str, Form(min_length=1, max_length=200)],
    routing_number: Annotated[str, Form(min_length=4, max_length=40)],
    account_number: Annotated[str, Form(min_length=4, max_length=40)],
    tax_form_file: UploadFile,
    bank_letter_file: UploadFile,
    phone: Annotated[str, Form(max_length=40)] = "",
    insurance_file: UploadFile | None = None,
) -> Response:
    """The vendor's details and documents. Bank details are accepted only here."""
    limit = service.MAX_DOC_BYTES
    files = []
    for kind, upload in (
        (DocumentKind.TAX_FORM, tax_form_file),
        (DocumentKind.BANK_LETTER, bank_letter_file),
        (DocumentKind.INSURANCE, insurance_file),
    ):
        if upload is None:
            continue
        data = await upload.read(limit + 1)
        files.append(
            (kind, upload.filename or kind.value, upload.content_type or "application/pdf", data)
        )
    await service.portal_submit(
        session,
        token,
        legal_name=legal_name,
        tax_id=tax_id,
        tax_form=tax_form,
        address=address,
        phone=phone,
        bank_name=bank_name,
        account_name=account_name,
        routing_number=routing_number,
        account_number=account_number,
        files=files,
        llm=llm,
        ctx=ctx,
    )
    return Response(status_code=204)
