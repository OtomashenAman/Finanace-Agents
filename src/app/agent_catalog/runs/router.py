import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, UploadFile, status

from src.app.agent_catalog.runs import service
from src.app.agent_catalog.runs.exceptions import DocumentTooLargeError
from src.app.agent_catalog.runs.schemas import (
    DocumentText,
    FormSpec,
    ReviewCreate,
    RunDetail,
    RunInputUpdate,
    RunSummary,
)
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
async def list_runs(key: str, session: SessionDep, user: CurrentUser) -> list[RunSummary]:
    return await service.list_runs(session, user, key)


@router.post(
    "/runs", response_model=RunDetail, status_code=status.HTTP_201_CREATED, responses=_ERRORS
)
async def create_run(
    key: str, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> RunDetail:
    """Start a new draft run (preparer only)."""
    return await service.create_run(session, user, key, ctx)


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
    """Approve, reject or request changes (assigned reviewer, never the preparer)."""
    return await service.review_run(session, user, key, run_id, body, ctx)
