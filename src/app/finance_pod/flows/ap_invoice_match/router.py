import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.case_api import CapacityRequiredError
from src.app.finance_pod.flows.ap_invoice_match.service import KEY, draft_bills_without_case
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.snapshots import service as snapshots

router = APIRouter(prefix="/apm", tags=["finance pod: invoice matching"])
_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (403, 404)}


class IntakeRequest(BaseModel):
    snapshot_id: uuid.UUID


class IntakeResult(BaseModel):
    opened: list[str]  # case references
    already: int  # invoices that had a case


@router.post("/intake", response_model=IntakeResult, responses=_ERRORS)
async def intake(
    body: IntakeRequest, session: SessionDep, access: FinanceAccessDep, ctx: RequestContextDep
) -> IntakeResult:
    """Open a matching case for every incoming invoice (ERPNext draft) of the snapshot that
    hasn't one (AP analyst)."""
    from src.app.service_pod.core.cases.service import open_case

    snapshot = await snapshots.load_snapshot(session, body.snapshot_id)
    if not access.holds(Cap.AP_ANALYST.value, snapshot.entity_id):
        raise CapacityRequiredError("Only an AP analyst takes invoices in.")
    taken = set(
        await session.scalars(
            select(PodCase.selection["bill_id"].astext).where(
                PodCase.workflow == KEY, PodCase.status != CaseStatus.CANCELLED
            )
        )
    )
    doc = snapshots.document(snapshot)
    bills = {b.id: b for b in doc.bills or []}
    opened = []
    for bill_id in draft_bills_without_case(doc, taken):
        bill = bills[bill_id]
        case = await open_case(
            session, access, KEY, snapshot,
            f"{bill.vendor_id} invoice {bill.bill_number or bill.id}", {"bill_id": bill_id}, ctx,
        )  # fmt: skip
        opened.append(case.reference)
    await session.commit()
    return IntakeResult(opened=opened, already=len(taken & set(bills)))
