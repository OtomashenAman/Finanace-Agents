import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, UploadFile

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.requests.exceptions import RequestInvalidError
from src.app.finance_pod.sourcing import service
from src.app.finance_pod.sourcing.schemas import (
    ChooseIn,
    NewQuoteIn,
    QuoteIn,
    QuoteRequestIn,
    SourcingOut,
)

router = APIRouter(prefix="/requests/{request_id}/sourcing")

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 503)
}
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]


@router.get("", response_model=SourcingOut, responses=_ERRORS)
async def get_sourcing(
    request_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> SourcingOut:
    """The sourcing agent's vendors, the quotes and the side-by-side comparison (1.3)."""
    return await service.view(session, request_id)


@router.post("/refresh", response_model=SourcingOut, responses=_ERRORS)
async def refresh(
    request_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> SourcingOut:
    await service.refresh(session, access, request_id, ctx)
    return await service.view(session, request_id)


@router.post("/quote-requests", response_model=SourcingOut, responses=_ERRORS)
async def request_quotes(
    request_id: uuid.UUID,
    body: QuoteRequestIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> SourcingOut:
    """Send the agent's quote request to the chosen vendors (1.3.1.b)."""
    await service.request_quotes(session, access, request_id, body, ctx)
    return await service.view(session, request_id)


@router.post("/quotes", response_model=SourcingOut, status_code=201, responses=_ERRORS)
async def add_quote(
    request_id: uuid.UUID,
    body: NewQuoteIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> SourcingOut:
    await service.add_quote(session, access, request_id, body, ctx)
    return await service.view(session, request_id)


@router.put("/quotes/{quote_id}", response_model=SourcingOut, responses=_ERRORS)
async def update_quote(
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    body: QuoteIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> SourcingOut:
    await service.update_quote(session, access, request_id, quote_id, body, ctx)
    return await service.view(session, request_id)


@router.post("/quotes/{quote_id}/file", response_model=SourcingOut, responses=_ERRORS)
async def attach_quote_file(
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    file: UploadFile,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: LLMDep,
) -> SourcingOut:
    """The quote document: kept, and read by the sourcing agent (figures checked)."""
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise RequestInvalidError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    await service.attach_quote_file(
        session,
        access,
        request_id,
        quote_id,
        file.filename or "quote",
        file.content_type or "application/octet-stream",
        data,
        llm,
        ctx,
    )
    return await service.view(session, request_id)


@router.get("/quotes/{quote_id}/file", responses=_ERRORS)
async def download_quote_file(
    request_id: uuid.UUID, quote_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> Response:
    filename, content_type, content = await service.quote_file(session, request_id, quote_id)
    return Response(
        content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename.replace(chr(34), "")}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/choose", response_model=SourcingOut, responses=_ERRORS)
async def choose(
    request_id: uuid.UUID,
    body: ChooseIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> SourcingOut:
    """The buyer confirms vendor and terms (1.3.2). A new vendor starts onboarding."""
    await service.choose(session, access, request_id, body, ctx)
    return await service.view(session, request_id)
