"""The vendor's secure portal (AP1 1.5.1.a): no account, only the signed link the invitation
carried. It names what to upload and takes the tax form, bank letter and compliance papers;
nothing of the company's data is shown. The link stops working when it expires, when a new one
is issued, or once the vendor is activated."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

import jwt
from fastapi import APIRouter, Form, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.security import decode_purpose_token
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.errors import AppError
from src.app.finance_pod.flows.ap_vendor_onboarding.agents import PORTAL
from src.app.service_pod.core.cases.models import LOCKED_STATUSES, CaseStatus, PodCase
from src.app.service_pod.core.messaging import service as messaging
from src.app.service_pod.core.messaging.models import ArtifactChannel, ArtifactKind, PodArtifact
from src.app.service_pod.core.snapshots.exceptions import SnapshotTooLargeError
from src.app.service_pod.core.workflows import WorkflowKey

router = APIRouter(prefix="/vendor-portal", tags=["vendor portal (public)"])
_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (404, 422)}
PORTAL_KINDS = {
    "tax_form": ArtifactKind.TAX_FORM,
    "bank_letter": ArtifactKind.BANK_LETTER,
    "compliance": ArtifactKind.COMPLIANCE,
}


class PortalLinkError(AppError):
    status_code = 404
    code = "portal_link_invalid"
    message = "This link isn't valid any more. Ask your contact for a new one."


class PortalDocument(BaseModel):
    kind: str
    filename: str
    uploaded_at: datetime


class PortalView(BaseModel):
    vendor_name: str
    expires_at: datetime
    required: list[str]
    optional: list[str]
    uploaded: list[PortalDocument]


async def _case(session: AsyncSession, token: str) -> PodCase:
    try:
        claims = decode_purpose_token(token, PORTAL)
        case_id = uuid.UUID(claims["case"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise PortalLinkError from exc
    case = await session.get(PodCase, case_id)
    if (
        case is None
        or case.workflow != WorkflowKey.AP_VENDOR_ONBOARDING
        or case.status in LOCKED_STATUSES
        or case.status == CaseStatus.APPROVED  # activated: uploads are closed
        or (case.state.get("portal") or {}).get("jti") != claims.get("jti")
    ):
        raise PortalLinkError
    return case


@router.get("/{token}", response_model=PortalView, responses=_ERRORS)
async def portal(token: str, session: SessionDep) -> PortalView:
    case = await _case(session, token)
    uploaded = list(
        await session.scalars(
            select(PodArtifact)
            .where(
                PodArtifact.case_id == case.id,
                PodArtifact.channel == ArtifactChannel.VENDOR_PORTAL,
            )
            .order_by(PodArtifact.created_at)
        )
    )
    return PortalView(
        vendor_name=case.selection["vendor_name"],
        expires_at=datetime.fromisoformat(case.state["portal"]["expires_at"]),
        required=["tax_form", "bank_letter"],
        optional=["compliance"],
        uploaded=[
            PortalDocument(kind=a.kind.value, filename=a.filename, uploaded_at=a.created_at)
            for a in uploaded
        ],
    )


@router.post(
    "/{token}/documents",
    response_model=PortalDocument,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def upload(
    token: str,
    file: UploadFile,
    kind: Annotated[Literal["tax_form", "bank_letter", "compliance"], Form()],
    session: SessionDep,
    ctx: RequestContextDep,
) -> PortalDocument:
    case = await _case(session, token)
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise SnapshotTooLargeError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    artifact = await messaging.add_artifact(
        session, case, PORTAL_KINDS[kind], [], file.filename or "document",
        file.content_type or "application/octet-stream", data, ctx,
        uploaded_by=None, channel=ArtifactChannel.VENDOR_PORTAL,
    )  # fmt: skip
    await session.commit()
    return PortalDocument(kind=kind, filename=artifact.filename, uploaded_at=artifact.created_at)
