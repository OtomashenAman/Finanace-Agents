import uuid
from typing import Any

from fastapi import APIRouter

from src.app.common.schemas import ErrorResponse
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep, for_workflow
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.bank_recon import views
from src.app.service_pod.flows.bank_recon.schemas import BankWorklist

# Every endpoint here is this workflow's: only people given it
router = APIRouter(
    prefix="/bank",
    tags=["service pod: bank-to-invoice"],
    dependencies=[for_workflow(WorkflowKey.BANK_RECON)],
)

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (403, 404)}


@router.get("/unapplied", response_model=BankWorklist, responses=_ERRORS)
async def bank_unapplied(
    session: SessionDep, _: PodAccessDep, snapshot_id: uuid.UUID | None = None
) -> BankWorklist:
    """Bank receipts not yet recorded in QuickBooks (default: the latest with receipts)."""
    return await views.bank_worklist(session, snapshot_id)
