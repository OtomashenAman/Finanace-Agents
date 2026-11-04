"""Purchase requests (Phase 1.1): written by the requester, enriched by the request agent,
submitted for the budget check once nothing blocking is left."""

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.llm.base import LLMProvider
from src.app.finance_pod.access import FinanceAccess
from src.app.finance_pod.approvals import service as approvals
from src.app.finance_pod.requests import agent
from src.app.finance_pod.requests.exceptions import (
    NotRequesterError,
    RequestFileNotFoundError,
    RequestInvalidError,
    RequestLockedError,
    RequestNotFoundError,
    StaleRequestError,
)
from src.app.finance_pod.requests.models import (
    EDITABLE,
    CodingSource,
    FpPurchaseRequest,
    FpRequestFile,
    FpRequestLine,
    RequestFileKind,
    RequestStatus,
)
from src.app.finance_pod.requests.schemas import (
    Enrichment,
    FileOut,
    LineOut,
    RequestDraft,
    RequestIn,
    RequestOut,
    RequestSummary,
)
from src.app.finance_pod.settings.service import current as current_settings

FILE_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# Cancellable by the requester (an approved request until it becomes a PO: frees its budget)
OPEN_STATUSES = frozenset(
    {
        RequestStatus.DRAFT,
        RequestStatus.SUBMITTED,
        RequestStatus.QUERIED,
        RequestStatus.APPROVED,
    }
)
_CODING = ("cost_centre_code", "lab_code", "project_code", "grant_code")


# --- reading --------------------------------------------------------------------------------


def _blocking(request: FpPurchaseRequest) -> int | None:
    if not request.enrichment:
        return None
    return sum(1 for p in request.enrichment.get("problems", []) if p.get("blocking"))


def _summary(request: FpPurchaseRequest, requester: str) -> dict[str, Any]:
    return {
        "id": request.id,
        "reference": request.reference,
        "title": request.title,
        "status": request.status,
        "requester_id": request.requester_id,
        "requester_name": requester,
        "total": request.total,
        "currency": request.currency,
        "cost_centre_code": request.cost_centre_code,
        "needed_by": request.needed_by,
        "submitted_at": request.submitted_at,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "blocking_problems": _blocking(request),
    }


async def list_requests(
    session: AsyncSession, status: RequestStatus | None, mine_for: User | None
) -> list[RequestSummary]:
    query = (
        select(FpPurchaseRequest, User.full_name)
        .join(User, User.id == FpPurchaseRequest.requester_id)
        .order_by(FpPurchaseRequest.number.desc())
    )
    if status is not None:
        query = query.where(FpPurchaseRequest.status == status)
    if mine_for is not None:
        query = query.where(FpPurchaseRequest.requester_id == mine_for.id)
    rows = await session.execute(query)
    return [RequestSummary(**_summary(r, name)) for r, name in rows]


async def _load(
    session: AsyncSession, request_id: uuid.UUID, *, lock: bool = False
) -> FpPurchaseRequest:
    request = await session.get(FpPurchaseRequest, request_id, with_for_update=lock)
    if request is None:
        raise RequestNotFoundError
    return request


async def _out(session: AsyncSession, request: FpPurchaseRequest, viewer: User) -> RequestOut:
    requester = await session.get(User, request.requester_id)
    files = await session.scalars(
        select(FpRequestFile)
        .where(FpRequestFile.request_id == request.id)
        .order_by(FpRequestFile.created_at)
    )
    decide = await approvals.view(session, request, viewer)
    return RequestOut(
        round=request.round,
        budget_check=decide.check,
        route=decide.route,
        current_step=decide.current,
        can_decide=decide.blocker is None,
        decide_blocker=decide.blocker,
        decisions=decide.decisions,
        **_summary(request, requester.full_name if requester else "a deleted user"),
        version=request.version,
        purpose=request.purpose,
        lab_code=request.lab_code,
        project_code=request.project_code,
        grant_code=request.grant_code,
        coding_source=request.coding_source,
        source_text=request.source_text,
        lines=[
            LineOut(
                description=ln.description,
                quantity=ln.quantity,
                unit=ln.unit,
                unit_price=ln.unit_price,
                category=ln.category,
                catalogue_item_code=ln.catalogue_item_code,
                amount=ln.amount,
            )
            for ln in request.lines
        ],
        files=[FileOut.model_validate(f, from_attributes=True) for f in files],
        enrichment=Enrichment.model_validate(request.enrichment) if request.enrichment else None,
        closed_at=request.closed_at,
        can_edit=request.status in EDITABLE and request.requester_id == viewer.id,
    )


async def request_out(
    session: AsyncSession, request: FpPurchaseRequest, viewer: User
) -> RequestOut:
    return await _out(session, request, viewer)


async def summaries(session: AsyncSession, ids: list[uuid.UUID]) -> list[RequestSummary]:
    """These requests, in the given order."""
    if not ids:
        return []
    rows = await session.execute(
        select(FpPurchaseRequest, User.full_name)
        .join(User, User.id == FpPurchaseRequest.requester_id)
        .where(FpPurchaseRequest.id.in_(ids))
    )
    found = {r.id: RequestSummary(**_summary(r, name)) for r, name in rows}
    return [found[i] for i in ids if i in found]


async def get_request(
    session: AsyncSession, access: FinanceAccess, request_id: uuid.UUID
) -> RequestOut:
    return await _out(session, await _load(session, request_id), access.user)


# --- changing -------------------------------------------------------------------------------


def _check_change(request: FpPurchaseRequest, access: FinanceAccess, version: int) -> None:
    if request.requester_id != access.user.id:
        raise NotRequesterError
    if request.version != version:
        raise StaleRequestError
    if request.status not in EDITABLE:
        raise RequestLockedError(
            f"{request.reference} is {request.status.value}; it can't be changed now."
        )


def _apply(request: FpPurchaseRequest, body: RequestIn) -> None:
    coding_changed = any(getattr(request, f) != getattr(body, f) for f in _CODING)
    request.title = body.title.strip()
    request.purpose = body.purpose.strip()
    request.needed_by = body.needed_by
    for f in _CODING:
        setattr(request, f, (getattr(body, f) or "").strip() or None)
    if coding_changed:
        request.coding_source = (
            CodingSource.REQUESTER if any(getattr(request, f) for f in _CODING) else None
        )
    if body.source_text is not None:
        request.source_text = body.source_text.strip() or None
    request.lines = [
        FpRequestLine(position=n, **line.model_dump()) for n, line in enumerate(body.lines, start=1)
    ]


async def _enrich(
    session: AsyncSession, request: FpPurchaseRequest, llm: LLMProvider | None = None
) -> Enrichment:
    result = await agent.enrich(session, request, await current_settings(session), llm=llm)
    request.enrichment = result.model_dump(mode="json")
    return result


async def create_request(
    session: AsyncSession, access: FinanceAccess, body: RequestIn, ctx: RequestContext
) -> RequestOut:
    settings = await current_settings(session)
    request = FpPurchaseRequest(
        requester_id=access.user.id,
        status=RequestStatus.DRAFT,
        currency=settings.currency,
        title="",
        lines=[],
    )
    _apply(request, body)
    session.add(request)
    await session.flush()
    await _enrich(session, request)
    record_event(
        session,
        "fpod.request_created",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        summary=f"Raised purchase request {request.reference}: {request.title}",
    )
    await session.commit()
    return await _out(session, request, access.user)


async def update_request(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    body: RequestIn,
    version: int,
    ctx: RequestContext,
) -> RequestOut:
    request = await _load(session, request_id, lock=True)
    _check_change(request, access, version)
    _apply(request, body)
    request.version += 1
    await session.flush()
    await _enrich(session, request)
    record_event(
        session,
        "fpod.request_updated",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        summary=f"Edited purchase request {request.reference}",
    )
    await session.commit()
    return await _out(session, request, access.user)


async def suggest_coding(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    llm: LLMProvider,
    ctx: RequestContext,
) -> RequestOut:
    """Run the request agent with AI: a fresh coding suggestion, plus the checks."""
    request = await _load(session, request_id, lock=True)
    if request.status not in EDITABLE:
        raise RequestLockedError(f"{request.reference} is {request.status.value}.")
    result = await _enrich(session, request, llm)
    suggestion = result.suggestion
    record_event(
        session,
        "fpod.request_enriched",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        suggestion=suggestion.model_dump(mode="json") if suggestion else None,
        note=result.suggestion_note,
        summary=(
            f"Request agent suggested coding for {request.reference}: "
            + (
                ", ".join(
                    f"{f.removesuffix('_code').replace('_', ' ')} {getattr(suggestion, f)}"
                    for f in _CODING
                    if getattr(suggestion, f)
                )
                if suggestion
                else f"none ({result.suggestion_note})"
            )
        ),
    )
    await session.commit()
    return await _out(session, request, access.user)


async def accept_suggestion(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    version: int,
    ctx: RequestContext,
) -> RequestOut:
    """The requester takes the agent's coding (and categories for lines without one)."""
    request = await _load(session, request_id, lock=True)
    _check_change(request, access, version)
    enrichment = Enrichment.model_validate(request.enrichment) if request.enrichment else None
    suggestion = enrichment.suggestion if enrichment else None
    if suggestion is None:
        raise RequestInvalidError("There's no coding suggestion to accept.")
    for f in _CODING:
        setattr(request, f, getattr(suggestion, f))
    request.coding_source = CodingSource.AGENT
    if len(suggestion.line_categories) == len(request.lines):
        for line, category in zip(request.lines, suggestion.line_categories, strict=True):
            if line.category is None and category:
                line.category = category.lower()
    request.version += 1
    await session.flush()
    await _enrich(session, request)
    record_event(
        session,
        "fpod.request_coding_accepted",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        source=suggestion.source,
        summary=f"Accepted the request agent's coding on {request.reference}",
    )
    await session.commit()
    return await _out(session, request, access.user)


async def submit(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    version: int,
    ctx: RequestContext,
) -> RequestOut:
    """Send it to the budget check (1.2). Refused while the agent flags anything blocking."""
    request = await _load(session, request_id, lock=True)
    _check_change(request, access, version)
    result = await _enrich(session, request)
    blocking = [p.message for p in result.problems if p.blocking]
    if blocking:
        await session.commit()  # keep the fresh check so the page shows it
        raise RequestInvalidError("Fix these first: " + " ".join(blocking))
    resubmitted = request.status == RequestStatus.QUERIED
    request.status = RequestStatus.SUBMITTED
    request.submitted_at = utcnow()
    request.round += 1  # a new round of the budget check and approvals
    request.version += 1
    check = await approvals.run_check(session, request)
    record_event(
        session,
        "fpod.budget_checked",
        ctx,
        actor_id=None,
        run=request.reference,
        request_id=str(request.id),
        round=request.round,
        findings=[f.model_dump() for f in check.findings],
        route=[f"{s.capacity}: {s.approver_email}" for s in check.route],
        summary=(
            f"Budget agent checked {request.reference}: "
            + (
                "; ".join(f.message for f in check.findings if f.severity != "info")
                or "within budget, nothing blocking"
            )
            + ". Route: "
            + (", ".join(s.capacity for s in check.route) or "none")
        ),
    )
    record_event(
        session,
        "fpod.request_submitted",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        total=str(request.total),
        currency=request.currency,
        summary=(
            f"{'Resubmitted' if resubmitted else 'Submitted'} purchase request "
            f"{request.reference} ({request.total} {request.currency}) for the budget check"
        ),
    )
    await session.commit()
    return await _out(session, request, access.user)


async def cancel(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    version: int,
    reason: str,
    ctx: RequestContext,
) -> RequestOut:
    request = await _load(session, request_id, lock=True)
    if request.requester_id != access.user.id:
        raise NotRequesterError
    if request.version != version:
        raise StaleRequestError
    if request.status not in OPEN_STATUSES:
        raise RequestLockedError(f"{request.reference} is already {request.status.value}.")
    if request.status == RequestStatus.APPROVED:
        from src.app.finance_pod.orders.models import FpPurchaseOrder, PoStatus

        if await session.scalar(
            select(FpPurchaseOrder.id).where(
                FpPurchaseOrder.request_id == request.id,
                FpPurchaseOrder.status != PoStatus.CANCELLED,
            )
        ):
            raise RequestLockedError("Cancel its PO first.")
        await approvals.release_commitments(session, request, f"cancelled: {reason}")
    request.status = RequestStatus.CANCELLED
    request.closed_at = utcnow()
    request.version += 1
    record_event(
        session,
        "fpod.request_cancelled",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        reason=reason,
        summary=f"Cancelled purchase request {request.reference}: {reason}",
    )
    await session.commit()
    return await _out(session, request, access.user)


async def draft_from_text(llm: LLMProvider, text: str) -> RequestDraft:
    return await agent.draft_from_text(llm, text)


# --- files ----------------------------------------------------------------------------------


async def upload_file(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    kind: RequestFileKind,
    filename: str,
    content_type: str,
    data: bytes,
    ctx: RequestContext,
) -> RequestOut:
    request = await _load(session, request_id, lock=True)
    if request.requester_id != access.user.id:
        raise NotRequesterError
    if request.status not in EDITABLE:
        raise RequestLockedError(f"{request.reference} is {request.status.value}.")
    content_type = content_type.split(";")[0].strip().lower()
    if content_type not in FILE_TYPES:
        raise RequestInvalidError("Allowed: PDF, PNG, JPEG, CSV, TXT, XLSX or DOCX.")
    if not data:
        raise RequestInvalidError("The file is empty.")
    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = await session.scalar(
        select(FpRequestFile.filename).where(
            FpRequestFile.request_id == request.id, FpRequestFile.sha256 == sha256
        )
    )
    if duplicate is not None:
        raise RequestInvalidError(f"This file is already attached as '{duplicate}'.")
    session.add(
        FpRequestFile(
            request_id=request.id,
            kind=kind,
            filename=filename[:255],
            content_type=content_type,
            size=len(data),
            sha256=sha256,
            content=data,
            uploaded_by=access.user.id,
        )
    )
    request.version += 1
    record_event(
        session,
        "fpod.request_file_added",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        sha256=sha256,
        summary=f"Attached {kind.value} '{filename[:255]}' to {request.reference}",
    )
    await session.commit()
    return await _out(session, request, access.user)


async def _file(session: AsyncSession, request_id: uuid.UUID, file_id: uuid.UUID) -> FpRequestFile:
    file = await session.get(FpRequestFile, file_id)
    if file is None or file.request_id != request_id:
        raise RequestFileNotFoundError
    return file


async def remove_file(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    file_id: uuid.UUID,
    ctx: RequestContext,
) -> RequestOut:
    request = await _load(session, request_id, lock=True)
    if request.requester_id != access.user.id:
        raise NotRequesterError
    if request.status not in EDITABLE:
        raise RequestLockedError(f"{request.reference} is {request.status.value}.")
    file = await _file(session, request_id, file_id)
    await session.delete(file)
    request.version += 1
    record_event(
        session,
        "fpod.request_file_removed",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        sha256=file.sha256,
        summary=f"Removed '{file.filename}' from {request.reference}",
    )
    await session.commit()
    return await _out(session, request, access.user)


async def file_content(
    session: AsyncSession, request_id: uuid.UUID, file_id: uuid.UUID
) -> tuple[FpRequestFile, bytes]:
    file = await _file(session, request_id, file_id)
    content = await session.scalar(select(FpRequestFile.content).where(FpRequestFile.id == file.id))
    return file, content or b""


async def status_counts(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(FpPurchaseRequest.status, func.count()).group_by(FpPurchaseRequest.status)
    )
    return {str(status): count for status, count in rows}
