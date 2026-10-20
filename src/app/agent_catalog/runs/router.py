import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response, UploadFile, status

from src.app.agent_catalog.runs import service
from src.app.agent_catalog.runs.exceptions import DocumentTooLargeError
from src.app.agent_catalog.runs.schemas import (
    DocumentText,
    FormSpec,
    ReviewCreate,
    RunCreate,
    RunDetail,
    RunInputUpdate,
    RunSummary,
    SourceLink,
)
from src.app.audit.schemas import AuditEventOut
from src.app.auth.dependencies import CurrentUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider

router = APIRouter(prefix="/agents/{key}", tags=["agent runs"])

LLM = Annotated[LLMProvider, Depends(get_llm_provider)]
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409)
}


@router.get("/form", response_model=FormSpec, responses=_ERRORS)
async def get_form(key: str, session: SessionDep, user: CurrentUser) -> FormSpec:
    """Fields of the agent's input form (drives the generated frontend form)."""
    return await service.get_form(session, user, key)


@router.get("/runs", response_model=list[RunSummary], responses=_ERRORS)
async def list_runs(
    key: str, session: SessionDep, user: CurrentUser, entity_id: uuid.UUID | None = None
) -> list[RunSummary]:
    return await service.list_runs(session, user, key, entity_id)


@router.post(
    "/runs", response_model=RunDetail, status_code=status.HTTP_201_CREATED, responses=_ERRORS
)
async def create_run(
    key: str,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    response: Response,
    body: RunCreate | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> RunDetail:
    """Start a new draft run for a legal entity you work for (preparer only).

    Send an Idempotency-Key header to make retries safe: the same key returns the same run
    (200 instead of 201)."""
    run, created = await service.create_run(
        session, user, key, body or RunCreate(), ctx, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return run


@router.get("/runs/{run_id}", response_model=RunDetail, responses=_ERRORS)
async def get_run(key: str, run_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> RunDetail:
    return await service.get_run(session, user, key, run_id)


@router.put("/runs/{run_id}/input", response_model=RunDetail, responses=_ERRORS)
async def update_input(
    key: str, run_id: uuid.UUID, body: RunInputUpdate, session: SessionDep, user: CurrentUser
) -> RunDetail:
    """Save the form (partial values allowed). Clears a previous analysis."""
    return await service.update_input(session, user, key, run_id, body.values)


@router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_ERRORS,
)
async def delete_run(
    key: str, run_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> Response:
    await service.delete_run(session, user, key, run_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/runs/{run_id}/analyze", response_model=RunDetail, responses=_ERRORS)
async def analyze_run(
    key: str,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    llm: LLM,
) -> RunDetail:
    """Validate, run the deterministic engine, then ask the LLM for an explanation."""
    return await service.analyze_run(session, user, key, run_id, ctx, llm)


@router.post(
    "/runs/{run_id}/documents",
    response_model=RunDetail,
    status_code=status.HTTP_201_CREATED,
    responses={**_ERRORS, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def add_document(
    key: str,
    run_id: uuid.UUID,
    file: UploadFile,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
) -> RunDetail:
    """Upload a file: its text is extracted and stored; the file itself is discarded."""
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise DocumentTooLargeError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    return await service.add_document(
        session, user, key, run_id, file.filename or "document", data, ctx
    )


@router.get(
    "/runs/{run_id}/documents/{document_id}", response_model=DocumentText, responses=_ERRORS
)
async def get_document_text(
    key: str, run_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DocumentText:
    return await service.get_document_text(session, user, key, run_id, document_id)


@router.delete(
    "/runs/{run_id}/documents/{document_id}", response_model=RunDetail, responses=_ERRORS
)
async def remove_document(
    key: str,
    run_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
) -> RunDetail:
    return await service.remove_document(session, user, key, run_id, document_id, ctx)


@router.post("/runs/{run_id}/submit", response_model=RunDetail, responses=_ERRORS)
async def submit_run(
    key: str, run_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> RunDetail:
    """Send an analyzed run to the reviewer (locks it and records the result hash)."""
    return await service.submit_run(session, user, key, run_id, ctx)


@router.post("/runs/{run_id}/reviews", response_model=RunDetail, responses=_ERRORS)
async def review_run(
    key: str,
    run_id: uuid.UUID,
    body: ReviewCreate,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
) -> RunDetail:
    """Approve, reject or request changes (Finance Admin only, own runs included)."""
    return await service.review_run(session, user, key, run_id, body, ctx)


@router.put("/runs/{run_id}/source", response_model=RunDetail, responses=_ERRORS)
async def link_source(
    key: str,
    run_id: uuid.UUID,
    body: SourceLink,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
) -> RunDetail:
    """Prefill the input from a record of one of your data sources (preparer only)."""
    return await service.link_source(session, user, key, run_id, body, ctx)


@router.delete("/runs/{run_id}/source", response_model=RunDetail, responses=_ERRORS)
async def unlink_source(
    key: str, run_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> RunDetail:
    return await service.unlink_source(session, user, key, run_id, ctx)


@router.get("/runs/{run_id}/timeline", response_model=list[AuditEventOut], responses=_ERRORS)
async def get_timeline(
    key: str, run_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[AuditEventOut]:
    """Who did what on this run, oldest first (from the audit trail)."""
    return await service.get_timeline(session, user, key, run_id)


@router.get(
    "/runs/{run_id}/evidence-pack",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}, **_ERRORS},
)
async def evidence_pack(
    key: str, run_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> Response:
    """Everything about the run in one ZIP, with a manifest of SHA-256 hashes (audited)."""
    data, filename = await service.evidence_pack(session, user, key, run_id, ctx)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/runs/{run_id}/write-back", response_model=RunDetail, responses=_ERRORS)
async def write_back(
    key: str,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    llm: LLM,
) -> RunDetail:
    """After approval: note the approval on the QuickBooks bill the run came from (preparer
    only; runs in the background, the receipt shows on the run)."""
    return await service.write_back(session, user, key, run_id, ctx, llm)
