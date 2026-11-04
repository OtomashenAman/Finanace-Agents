import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, EmailStr, Field

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.payments import service
from src.app.finance_pod.payments.models import QueryStatus
from src.app.finance_pod.payments.service import CallbackIn

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]


class VersionIn(BaseModel):
    expected_version: int


class ExcludeIn(VersionIn):
    excluded: bool
    reason: str = Field(default="", max_length=1000)


class ApproveIn(VersionIn):
    note: str = Field(default="", max_length=1000)


class CancelIn(VersionIn):
    reason: str = Field(min_length=3, max_length=1000)


class QueryIn(BaseModel):
    from_email: EmailStr
    invoice_number: str | None = Field(default=None, max_length=80)
    question: str = Field(min_length=5, max_length=4000)


class ReplyIn(BaseModel):
    answer: str = Field(min_length=3, max_length=8000)


# Finance Admins (FinanceAccessDep on every route)
router = APIRouter()


@router.get("/payment-runs")
async def list_runs(session: SessionDep, _: FinanceAccessDep) -> list[dict[str, Any]]:
    return await service.list_runs(session)


@router.post("/payment-runs", status_code=201, responses=_ERRORS)
async def propose(
    session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> dict[str, Any]:
    """The payment agent proposes a run: approved invoices due soon or with a discount to take."""
    run = await service.propose(session, access, ctx)
    return await service.detail(session, run.id, access.user)


@router.get("/payment-runs/{run_id}", responses=_ERRORS)
async def get_run(
    run_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> dict[str, Any]:
    return await service.detail(session, run_id, access.user)


@router.post("/payment-runs/{run_id}/items/{item_id}/exclude", responses=_ERRORS)
async def exclude(
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ExcludeIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> dict[str, Any]:
    await service.set_excluded(
        session, access, run_id, item_id, body.expected_version, body.excluded, body.reason, ctx
    )
    return await service.detail(session, run_id, access.user)


@router.post("/payment-runs/{run_id}/items/{item_id}/callback", responses=_ERRORS)
async def callback(
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CallbackIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> dict[str, Any]:
    """The analyst's call-back on a payment to changed bank details."""
    await service.confirm_callback(session, access, run_id, item_id, body, ctx)
    return await service.detail(session, run_id, access.user)


@router.post("/payment-runs/{run_id}/approve", responses=_ERRORS)
async def approve(
    run_id: uuid.UUID,
    body: ApproveIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> dict[str, Any]:
    """Treasury's release: the second, by another person, releases the run."""
    await service.approve(session, access, run_id, body.expected_version, body.note, ctx)
    return await service.detail(session, run_id, access.user)


@router.post("/payment-runs/{run_id}/cancel", responses=_ERRORS)
async def cancel(
    run_id: uuid.UUID,
    body: CancelIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> dict[str, Any]:
    await service.cancel(session, access, run_id, body.expected_version, body.reason, ctx)
    return await service.detail(session, run_id, access.user)


class DeleteIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


@router.post("/payment-runs/delete", responses=_ERRORS)
async def delete_runs(
    body: DeleteIn, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> dict[str, int]:
    """Delete runs (to run a demo again): paid invoices go back to ready to pay."""
    return {"deleted": await service.delete_runs(session, access, body.ids, ctx)}


@router.delete("/payment-runs/{run_id}", responses=_ERRORS)
async def delete_run(
    run_id: uuid.UUID, session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> dict[str, int]:
    return {"deleted": await service.delete_runs(session, access, [run_id], ctx)}


@router.get("/payment-runs/{run_id}/bank-file", responses=_ERRORS)
async def bank_file(run_id: uuid.UUID, session: SessionDep, _: FinanceAccessDep) -> Response:
    name, data = await service.bank_file(session, run_id)
    return Response(
        data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/vendor-queries")
async def list_queries(
    session: SessionDep,
    _: FinanceAccessDep,
    status_filter: Annotated[QueryStatus | None, Query(alias="status")] = None,
) -> list[dict[str, Any]]:
    return await service.list_queries(session, status_filter)


@router.post("/vendor-queries", status_code=201, responses=_ERRORS)
async def log_query(
    body: QueryIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
    llm: LLMDep,
) -> dict[str, Any]:
    """A query that came by phone or email: the vendor agent answers it like a portal one."""
    q = await service.ask(
        session,
        from_email=str(body.from_email),
        invoice_number=body.invoice_number,
        question=body.question,
        via="app",
        llm=llm,
        ctx=ctx,
        actor=access.user,
    )
    return {"id": q.id, "reference": q.reference, "status": q.status}


@router.post("/vendor-queries/{query_id}/reply", responses=_ERRORS)
async def reply(
    query_id: uuid.UUID,
    body: ReplyIn,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> dict[str, Any]:
    q = await service.reply(session, access, query_id, body.answer, ctx)
    return {"id": q.id, "reference": q.reference, "status": q.status}


@router.get("/measures/payments")
async def payment_measures(session: SessionDep, _: FinanceAccessDep) -> dict[str, Any]:
    """On-time payment rate, discounts captured, query response time."""
    return await service.measures(session)


# Vendors' self-service help (no login): answers go to the email we hold for the vendor
help_router = APIRouter(prefix="/vendor-help", tags=["vendor help"])


@help_router.post("", status_code=202, responses=_ERRORS)
async def vendor_help(
    body: QueryIn, session: SessionDep, ctx: RequestContextDep, llm: LLMDep
) -> dict[str, str]:
    q = await service.ask(
        session,
        from_email=str(body.from_email),
        invoice_number=body.invoice_number,
        question=body.question,
        via="portal",
        llm=llm,
        ctx=ctx,
    )
    # The same reply either way: nothing about our records shows on the page
    return {
        "reference": q.reference,
        "message": "Thank you. If this email is the one we hold for your company, the answer is "
        "on its way there; questions we can't answer from our records go to our team.",
    }
