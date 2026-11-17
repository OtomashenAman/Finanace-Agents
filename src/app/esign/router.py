import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, Header, Query, Request, Response, UploadFile, status
from pydantic import ValidationError

from src.app.auth.dependencies import CurrentUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.esign import service
from src.app.esign.exceptions import TemplateRejectedError, TemplateTooLargeError
from src.app.esign.schemas import (
    DocumentDetail,
    DocumentOut,
    DocumentPage,
    EsignReport,
    EsignSetup,
    SendRequest,
    SignatureLayout,
    SigningSession,
    Stage,
    TemplateOut,
)

router = APIRouter(prefix="/esign", tags=["e-signature"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 404, 409, 413, 422, 502, 503)
}
_WEBHOOK_MAX_BYTES = 2 * 1024 * 1024


def _file(name: str, content_type: str, data: bytes) -> Response:
    safe = name.replace('"', "")
    return Response(
        data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/setup", response_model=EsignSetup)
async def setup(_: CurrentUser) -> EsignSetup:
    return service.setup()


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(session: SessionDep, user: CurrentUser) -> list[TemplateOut]:
    """Your own templates."""
    return await service.list_templates(session, user)


@router.post(
    "/templates",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def upload_template(
    file: UploadFile,
    name: Annotated[str, Form(max_length=200)],
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    description: Annotated[str | None, Form(max_length=2000)] = None,
    placement: Annotated[Literal["position", "tags"], Form()] = "position",
    page: Annotated[int | None, Form()] = None,
    x: Annotated[float | None, Form()] = None,
    y: Annotated[float | None, Form()] = None,
    width: Annotated[float | None, Form()] = None,
    height: Annotated[float | None, Form()] = None,
) -> TemplateOut:
    """placement "position": a signature box at page/x/y/width/height (the server's
    PANDADOC_SIGNATURE_* for any left out); "tags": the file has PandaDoc field tags."""
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise TemplateTooLargeError(f"Templates can be at most {limit // (1024 * 1024)} MB.")
    layout = None
    if placement == "position":
        given = {"page": page, "x": x, "y": y, "width": width, "height": height}
        try:
            layout = SignatureLayout.model_validate(
                service.default_layout().model_dump()
                | {k: v for k, v in given.items() if v is not None}
            )
        except ValidationError as exc:
            raise TemplateRejectedError(
                "The signature position is out of range: page from 1, x/y from 0, "
                "width and height above 0."
            ) from exc
    return await service.upload_template(
        session, user, name, description, file.filename or "template", data, layout, ctx
    )


@router.get("/templates/{template_id}/file", responses=_ERRORS)
async def template_file(template_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    return _file(*await service.template_file(session, user, template_id))


@router.delete(
    "/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS
)
async def delete_template(
    template_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> None:
    await service.delete_template(session, user, template_id, ctx)


@router.get("/documents", response_model=DocumentPage)
async def list_documents(
    session: SessionDep,
    user: CurrentUser,
    stage: Stage | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentPage:
    """Only the documents you sent."""
    return await service.list_documents(session, user, stage, search, limit, offset)


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def send_document(
    body: SendRequest, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> DocumentOut:
    """Send a template for signature: PandaDoc emails each signer a link."""
    return await service.send_document(session, user, body, ctx)


@router.get("/documents/{document_id}", response_model=DocumentDetail, responses=_ERRORS)
async def document_detail(
    document_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DocumentDetail:
    return await service.document_detail(session, user, document_id)


@router.post("/documents/{document_id}/refresh", response_model=DocumentDetail, responses=_ERRORS)
async def refresh_document(
    document_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> DocumentDetail:
    return await service.refresh_document(session, user, document_id)


@router.post("/documents/{document_id}/send", response_model=DocumentOut, responses=_ERRORS)
async def retry_send(
    document_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> DocumentOut:
    return await service.retry_send(session, user, document_id, ctx)


@router.post(
    "/documents/{document_id}/countersign", response_model=SigningSession, responses=_ERRORS
)
async def countersign(
    document_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> SigningSession:
    """Your signing session (embedded), once every other signer has signed."""
    return await service.countersign_session(session, user, document_id, ctx)


@router.get("/documents/{document_id}/download", responses=_ERRORS)
async def download(document_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    name, data = await service.download(session, user, document_id)
    return _file(name, "application/pdf", data)


@router.get("/report", response_model=EsignReport)
async def report(session: SessionDep, user: CurrentUser) -> EsignReport:
    """Your documents only: nobody else's sends are counted."""
    return await service.report(session, user)


@router.post("/webhook", responses=_ERRORS)
async def webhook(
    request: Request,
    session: SessionDep,
    signature: str | None = None,
    x_pandadoc_webhook_event_id: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    """PandaDoc's webhook (no login: the HMAC signature of the body is the key)."""
    body = await request.body()
    if len(body) > _WEBHOOK_MAX_BYTES:
        body = b"[]"
    applied = await service.handle_webhook(session, body, signature, x_pandadoc_webhook_event_id)
    return {"applied": applied}
