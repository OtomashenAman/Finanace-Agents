from fastapi import APIRouter

from src.app.common.context import RequestContextDep
from src.app.core.db import SessionDep
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.settings import service
from src.app.finance_pod.settings.schemas import FinanceSettingsOut, FinanceSettingsUpdate

router = APIRouter(prefix="/settings")


@router.get("", response_model=FinanceSettingsOut)
async def get_settings(session: SessionDep, _: FinanceAccessDep) -> FinanceSettingsOut:
    return await service.get_settings(session)


@router.put("", response_model=FinanceSettingsOut)
async def update_settings(
    body: FinanceSettingsUpdate,
    session: SessionDep,
    ctx: RequestContextDep,
    access: FinanceAccessDep,
) -> FinanceSettingsOut:
    """Purchasing threshold, quotes required above it, and the self-approval switch."""
    return await service.update_settings(session, body, access.user, ctx)
