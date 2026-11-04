import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Query, Response, UploadFile, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.requests import service
from src.app.finance_pod.requests.exceptions import RequestInvalidError
from src.app.finance_pod.requests.models import RequestFileKind, RequestStatus
from src.app.finance_pod.requests.schemas import (
    CancelIn,
    RequestDraft,
    RequestIn,
    RequestOut,
    RequestSummary,
    RequestUpdate,
    TextIn,
    VersionIn,
)

router = APIRouter(prefix="/requests")

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]


@router.get("", response_model=list[RequestSummary])
async def list_requests(
    session: SessionDep,
    access: FinanceAccessDep,
    status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None,
    mine: bool = False,
) -> list[RequestSummary]:
    return await service.list_requests(session, status_filter, access.user if mine else None)


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED, responses=_ERRORS)
async def create_request(
    body: RequestIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> RequestOut:
    """A draft; the request agent checks it straight away (prices, missing data)."""
    return await service.create_request(session, access, body, ctx)


@router.post("/draft-from-text", response_model=RequestDraft, responses=_ERRORS)
async def draft_from_text(body: TextIn, llm: LLMDep, _: FinanceAccessDep) -> RequestDraft:
    """Describe the need in your own words; the agent fills the form. Nothing is saved."""
    return await service.draft_from_text(llm, body.text)


@router.get("/{request_id}", response_model=RequestOut, responses=_ERRORS)
async def get_request(
    request_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> RequestOut:
    return await service.get_request(session, access, request_id)


@router.put("/{request_id}", response_model=RequestOut, responses=_ERRORS)
async def update_request(
    request_id: uuid.UUID,
    body: RequestUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    return await service.update_request(
        session, access, request_id, body, body.expected_version, ctx
    )


@router.post("/{request_id}/suggest", response_model=RequestOut, responses=_ERRORS)
async def suggest_coding(
    request_id: uuid.UUID,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: LLMDep,
) -> RequestOut:
    """Ask the request agent for cost centre, lab, project, grant and line categories."""
    return await service.suggest_coding(session, access, request_id, llm, ctx)


@router.post("/{request_id}/accept-suggestion", response_model=RequestOut, responses=_ERRORS)
async def accept_suggestion(
    request_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    return await service.accept_suggestion(session, access, request_id, body.expected_version, ctx)


@router.post("/{request_id}/submit", response_model=RequestOut, responses=_ERRORS)
async def submit(
    request_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    """To the budget check. Refused while anything blocking is flagged."""
    return await service.submit(session, access, request_id, body.expected_version, ctx)


@router.post("/{request_id}/cancel", response_model=RequestOut, responses=_ERRORS)
async def cancel(
    request_id: uuid.UUID,
    body: CancelIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    return await service.cancel(
        session, access, request_id, body.expected_version, body.reason, ctx
    )


@router.post(
    "/{request_id}/files",
    response_model=RequestOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def upload_file(
    request_id: uuid.UUID,
    file: UploadFile,
    kind: Annotated[RequestFileKind, Form()],
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    """A quote (1.1.1.b) or other supporting document."""
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise RequestInvalidError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    return await service.upload_file(
        session,
        access,
        request_id,
        kind,
        file.filename or "document",
        file.content_type or "application/octet-stream",
        data,
        ctx,
    )


@router.delete("/{request_id}/files/{file_id}", response_model=RequestOut, responses=_ERRORS)
async def remove_file(
    request_id: uuid.UUID,
    file_id: uuid.UUID,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    return await service.remove_file(session, access, request_id, file_id, ctx)


@router.get("/{request_id}/files/{file_id}", responses=_ERRORS)
async def download_file(
    request_id: uuid.UUID, file_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep
) -> Response:
    file, content = await service.file_content(session, request_id, file_id)
    safe = file.filename.replace('"', "")
    return Response(
        content,
        media_type=file.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
