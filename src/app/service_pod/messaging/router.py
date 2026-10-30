import re
import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Form, Response, UploadFile, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.service_pod.access.service import PodAccessDep
from src.app.service_pod.messaging import service
from src.app.service_pod.messaging.models import ArtifactKind, MessageStatus
from src.app.service_pod.messaging.schemas import (
    ArtifactDecision,
    ArtifactOut,
    EmailStatus,
    MessageDraftIn,
    MessageOut,
    MessageReconcile,
    MessageUpdate,
    MessageVersion,
    ReplyImport,
)
from src.app.service_pod.snapshots.exceptions import SnapshotTooLargeError

router = APIRouter(tags=["service pod: messages"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 413, 422)
}


@router.get("/email-status", response_model=EmailStatus)
async def email_status(_: PodAccessDep) -> EmailStatus:
    """Which transport approved mail uses and whether it's ready. Never sends anything."""
    return await service.email_status()


@router.get("/messages", response_model=list[MessageOut])
async def list_messages(
    session: SessionDep, access: PodAccessDep, status: MessageStatus | None = None
) -> list[MessageOut]:
    return await service.list_messages(session, access, status)


@router.post(
    "/cases/{case_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_draft(
    case_id: uuid.UUID,
    body: MessageDraftIn,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    return await service.create_draft(session, access, case_id, body, ctx)


@router.patch("/messages/{message_id}", response_model=MessageOut, responses=_ERRORS)
async def update_message(
    message_id: uuid.UUID,
    body: MessageUpdate,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    """Edit a draft (an approved message goes back to draft and needs approval again)."""
    return await service.update_message(session, access, message_id, body, ctx)


@router.post("/messages/{message_id}/approve", response_model=MessageOut, responses=_ERRORS)
async def approve_message(
    message_id: uuid.UUID,
    body: MessageVersion,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    return await service.approve_message(session, access, message_id, body.expected_version, ctx)


@router.post("/messages/{message_id}/send", response_model=MessageOut, responses=_ERRORS)
async def send_message(
    message_id: uuid.UUID,
    body: MessageVersion,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    """Send an approved message once (a repeated click never sends it twice)."""
    return await service.send_message(session, access, message_id, body.expected_version, ctx)


@router.post("/messages/{message_id}/reconcile", response_model=MessageOut, responses=_ERRORS)
async def reconcile_message(
    message_id: uuid.UUID,
    body: MessageReconcile,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    return await service.reconcile_message(session, access, message_id, body, ctx)


@router.post("/cases/{case_id}/replies", response_model=MessageOut, responses=_ERRORS)
async def import_reply(
    case_id: uuid.UUID,
    body: ReplyImport,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
) -> MessageOut:
    """Import a customer reply (201; 200 when the same email was imported before)."""
    reply, created = await service.import_reply(session, access, case_id, body, ctx)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return reply


@router.post(
    "/cases/{case_id}/artifacts",
    response_model=ArtifactOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def upload_artifact(
    case_id: uuid.UUID,
    file: UploadFile,
    kind: Annotated[ArtifactKind, Form()],
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    invoice_refs: Annotated[str, Form(max_length=2000)] = "",
) -> ArtifactOut:
    """A supporting document for some of the case's invoices (comma-separated numbers)."""
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise SnapshotTooLargeError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    refs = [r.strip() for r in invoice_refs.split(",") if r.strip()]
    return await service.upload_artifact(
        session,
        access,
        case_id,
        kind,
        refs,
        file.filename or "document",
        file.content_type or "application/octet-stream",
        data,
        ctx,
    )


@router.post("/artifacts/{artifact_id}/decision", response_model=ArtifactOut, responses=_ERRORS)
async def decide_artifact(
    artifact_id: uuid.UUID,
    body: ArtifactDecision,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> ArtifactOut:
    return await service.decide_artifact(session, access, artifact_id, body.decision, ctx)


@router.get("/artifacts/{artifact_id}/content", responses=_ERRORS)
async def artifact_content(
    artifact_id: uuid.UUID, session: SessionDep, access: PodAccessDep
) -> Response:
    artifact, content = await service.artifact_content(session, access, artifact_id)
    return Response(
        content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{re.sub(r"[^A-Za-z0-9._-]", "_", artifact.filename)}"; '
                f"filename*=UTF-8''{quote(artifact.filename)}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
