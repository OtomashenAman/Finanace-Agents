import uuid
from typing import Any

from fastapi import APIRouter

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.approvals import service
from src.app.finance_pod.approvals.schemas import DecisionIn
from src.app.finance_pod.requests import service as requests_service
from src.app.finance_pod.requests.schemas import RequestOut, RequestSummary

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}


@router.get("/approvals", response_model=list[RequestSummary])
async def waiting_for_me(session: SessionDep, access: FinanceAccessDep) -> list[RequestSummary]:
    """Submitted requests whose current approval step you can decide now, oldest first."""
    ids = await service.waiting_for(session, access.user)
    return await requests_service.summaries(session, ids)


@router.post("/requests/{request_id}/decide", response_model=RequestOut, responses=_ERRORS)
async def decide(
    request_id: uuid.UUID,
    body: DecisionIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> RequestOut:
    """Approve, reject or query the current step (1.2.2)."""
    request = await service.decide(
        session,
        access,
        request_id,
        body.expected_version,
        body.decision,
        body.note,
        body.acknowledge_budget,
        ctx,
    )
    return await requests_service.request_out(session, request, access.user)


@router.post("/requests/{request_id}/budget-check", response_model=RequestOut, responses=_ERRORS)
async def recheck(
    request_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> RequestOut:
    """Run the budget agent again (only before any step is decided)."""
    request = await service.recheck(session, access, request_id, ctx)
    return await requests_service.request_out(session, request, access.user)
