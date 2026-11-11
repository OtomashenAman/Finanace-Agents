from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.context import RequestContext
from src.app.finance_pod.settings.models import (
    DEFAULT_MIN_QUOTES,
    DEFAULT_PRICE_AMOUNT,
    DEFAULT_PRICE_PCT,
    DEFAULT_THRESHOLD,
    SETTINGS_ROW,
    FinancePodSettings,
)
from src.app.finance_pod.settings.schemas import FinanceSettingsOut, FinanceSettingsUpdate


async def current(session: AsyncSession) -> FinancePodSettings:
    """The settings in force (an unsaved row with the defaults when none was saved)."""
    row = await session.get(FinancePodSettings, SETTINGS_ROW)
    return row or FinancePodSettings(
        id=SETTINGS_ROW,
        currency="USD",
        purchasing_threshold=DEFAULT_THRESHOLD,
        min_quotes=DEFAULT_MIN_QUOTES,
        allow_self_approval=False,
        price_tolerance_pct=DEFAULT_PRICE_PCT,
        price_tolerance_amount=DEFAULT_PRICE_AMOUNT,
        qty_tolerance_pct=Decimal("0.00"),
        payment_horizon_days=7,
        cash_available=None,
        unusual_payment_amount=Decimal("25000.00"),
        bank_change_days=30,
        max_new_client_limit=Decimal("50000.00"),
        credit_review_days=365,
        estimate_tolerance_pct=Decimal("10.00"),
    )


def _out(row: FinancePodSettings) -> FinanceSettingsOut:
    return FinanceSettingsOut(
        currency=row.currency,
        purchasing_threshold=row.purchasing_threshold,
        min_quotes=row.min_quotes,
        allow_self_approval=row.allow_self_approval,
        price_tolerance_pct=row.price_tolerance_pct,
        price_tolerance_amount=row.price_tolerance_amount,
        qty_tolerance_pct=row.qty_tolerance_pct,
        payment_horizon_days=row.payment_horizon_days,
        cash_available=row.cash_available,
        unusual_payment_amount=row.unusual_payment_amount,
        bank_change_days=row.bank_change_days,
        max_new_client_limit=row.max_new_client_limit,
        credit_review_days=row.credit_review_days,
        estimate_tolerance_pct=row.estimate_tolerance_pct,
        updated_at=row.updated_at,  # None on the unsaved defaults
    )


async def get_settings(session: AsyncSession) -> FinanceSettingsOut:
    return _out(await current(session))


async def update_settings(
    session: AsyncSession, body: FinanceSettingsUpdate, actor: User, ctx: RequestContext
) -> FinanceSettingsOut:
    row = await session.get(FinancePodSettings, SETTINGS_ROW, with_for_update=True)
    if row is None:
        row = FinancePodSettings(id=SETTINGS_ROW)
        session.add(row)
    values = {
        k: v for k, v in body.model_dump(exclude={"clear_cash_available"}).items() if v is not None
    }
    if body.clear_cash_available:
        values["cash_available"] = None
    changes = {k: str(v) for k, v in values.items() if getattr(row, k, None) != v}
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_by = actor.id
    if changes:
        record_event(
            session,
            "fpod.settings_updated",
            ctx,
            actor_id=actor.id,
            summary="Changed Finance POD settings: "
            + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in changes.items()),
            **changes,
        )
    await session.commit()
    await session.refresh(row)
    return _out(row)
