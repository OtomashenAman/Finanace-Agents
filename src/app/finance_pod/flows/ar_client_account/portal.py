"""The client's secure portal (AR1 1.1.1): no account, only the signed link the invitation
carried. The client uploads their tax form and registration papers and submits the
application form, which completes step 1.1.1 (the client is the person of that step). Nothing
of the company's data is shown. The link stops working when it expires, when a new one is
issued, or once the credit decision is made."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

import jwt
from fastapi import APIRouter, Form, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.security import decode_purpose_token
from src.app.common.clock import utcnow
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.errors import AppError
from src.app.finance_pod.flows.ar_client_account.agents import PORTAL
from src.app.finance_pod.flows.ar_client_account.results import Application, DocumentsUploaded
from src.app.service_pod.core.cases.models import LOCKED_STATUSES, CaseStatus, PodCase
from src.app.service_pod.core.messaging import service as messaging
from src.app.service_pod.core.messaging.models import ArtifactChannel, ArtifactKind, PodArtifact
from src.app.service_pod.core.snapshots.exceptions import SnapshotTooLargeError
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.spec import StepStatus
from src.app.service_pod.core.workflows import WorkflowKey

router = APIRouter(prefix="/client-portal", tags=["client portal (public)"])
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (404, 409, 422)
}
PORTAL_KINDS = {"tax_form": ArtifactKind.TAX_FORM, "registration": ArtifactKind.COMPLIANCE}
KIND_NAMES = {kind: name for name, kind in PORTAL_KINDS.items()}  # as the client knows them


class PortalLinkError(AppError):
    status_code = 404
    code = "portal_link_invalid"
    message = "This link isn't valid any more. Ask your contact for a new one."


class ApplicationRefusedError(AppError):
    status_code = 409
    code = "application_refused"


class ApplicationInvalidError(AppError):
    status_code = 422
    code = "application_invalid"


class PortalDocument(BaseModel):
    kind: str
    filename: str
    uploaded_at: datetime


class ClientPortalView(BaseModel):
    client_name: str
    expires_at: datetime
    required: list[str]
    uploaded: list[PortalDocument]
    application: dict[str, Any] | None  # what the client submitted (theirs to see)
    open: bool  # the application can still be (re)submitted


async def _case(session: AsyncSession, token: str) -> PodCase:
    try:
        claims = decode_purpose_token(token, PORTAL)
        case_id = uuid.UUID(claims["case"])
    except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
        raise PortalLinkError from exc
    case = await session.get(PodCase, case_id)
    if (
        case is None
        or case.workflow != WorkflowKey.AR_CLIENT_ACCOUNT
        or case.status in LOCKED_STATUSES
        or case.status == CaseStatus.APPROVED  # decided: the application is closed
        or (case.state.get("portal") or {}).get("jti") != claims.get("jti")
    ):
        raise PortalLinkError
    return case


async def _rows(session: AsyncSession, case: PodCase) -> dict[str, PodCaseStep]:
    rows = await session.scalars(select(PodCaseStep).where(PodCaseStep.case_id == case.id))
    return {r.l5_code: r for r in rows}


def _open(rows: dict[str, PodCaseStep]) -> bool:
    """The client may (re)submit until the onboarding agent has accepted the application."""
    return rows["1.1.2.a"].status != StepStatus.DONE


async def _uploaded(session: AsyncSession, case: PodCase) -> list[PodArtifact]:
    return list(
        await session.scalars(
            select(PodArtifact)
            .where(
                PodArtifact.case_id == case.id,
                PodArtifact.channel == ArtifactChannel.CLIENT_PORTAL,
            )
            .order_by(PodArtifact.created_at)
        )
    )


@router.get("/{token}", response_model=ClientPortalView, responses=_ERRORS)
async def portal(token: str, session: SessionDep) -> ClientPortalView:
    case = await _case(session, token)
    rows = await _rows(session, case)
    return ClientPortalView(
        client_name=case.selection["client_name"],
        expires_at=datetime.fromisoformat(case.state["portal"]["expires_at"]),
        required=["tax_form", "registration"],
        uploaded=[
            PortalDocument(
                kind=KIND_NAMES.get(a.kind, a.kind.value),
                filename=a.filename,
                uploaded_at=a.created_at,
            )
            for a in await _uploaded(session, case)
        ],
        application=rows["1.1.1.a"].result,
        open=_open(rows),
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
    kind: Annotated[Literal["tax_form", "registration"], Form()],
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
        uploaded_by=None, channel=ArtifactChannel.CLIENT_PORTAL,
    )  # fmt: skip
    await session.commit()
    return PortalDocument(kind=kind, filename=artifact.filename, uploaded_at=artifact.created_at)


@router.post("/{token}/application", response_model=ClientPortalView, responses=_ERRORS)
async def submit(
    token: str, body: dict[str, Any], session: SessionDep, ctx: RequestContextDep
) -> ClientPortalView:
    """The client's form: completes 1.1.1 (a: the form, b: the documents they uploaded)."""
    case = await _case(session, token)
    rows = await _rows(session, case)
    if not _open(rows):
        raise ApplicationRefusedError("The application is being decided: it can't change now.")
    try:
        form = Application.model_validate(body)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ApplicationInvalidError(f"{where}: {first['msg']}") from exc
    uploaded = await _uploaded(session, case)
    tax = [a for a in uploaded if a.kind == ArtifactKind.TAX_FORM]
    if not tax:
        raise ApplicationRefusedError("Upload your tax form first, then submit the application.")
    documents = DocumentsUploaded(
        tax_form_id=tax[-1].id,
        registration_ids=[a.id for a in uploaded if a.kind == ArtifactKind.COMPLIANCE],
    )
    now = utcnow()
    for code, value in (("1.1.1.a", form), ("1.1.1.b", documents)):
        row = rows[code]
        row.status = StepStatus.DONE
        row.result = value.model_dump(mode="json")
        row.note = f"Submitted by {case.selection['contact_email']} through the client portal"
        row.done_by, row.done_at = None, now
    # A resubmission (after gaps were flagged) is read again by the onboarding agent
    for code in ("1.1.2.a", "1.1.2.b", "1.1.2.c"):
        if rows[code].status == StepStatus.FAILED:
            rows[code].status, rows[code].note = StepStatus.PENDING, None
    case.version += 1
    record_event(
        session, "pod.client_application", ctx, actor_id=None, case_id=str(case.id),
        summary=f"{case.reference}: {form.legal_name} submitted its application through the "
                "client portal",
    )  # fmt: skip
    await session.commit()
    return await portal(token, session)
