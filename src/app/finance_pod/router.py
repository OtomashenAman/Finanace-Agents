from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from src.app.common.context import RequestContextDep
from src.app.core.db import SessionDep
from src.app.finance_pod import demo
from src.app.finance_pod import measures as measures_module
from src.app.finance_pod.access import FinanceAccessDep
from src.app.finance_pod.approvals import service as approvals_service
from src.app.finance_pod.approvals.router import router as approvals_router
from src.app.finance_pod.billing import service as billing_service
from src.app.finance_pod.billing.router import router as billing_router
from src.app.finance_pod.clients import service as clients_service
from src.app.finance_pod.clients.router import router as clients_router
from src.app.finance_pod.invoices import service as invoices_service
from src.app.finance_pod.invoices.models import ExceptionStatus, FpInvoice, FpInvoiceException
from src.app.finance_pod.invoices.router import router as invoices_router
from src.app.finance_pod.onboarding.models import FpOnboarding, OnboardingStatus
from src.app.finance_pod.onboarding.router import router as onboarding_router
from src.app.finance_pod.orders import service as orders_service
from src.app.finance_pod.orders.router import router as orders_router
from src.app.finance_pod.payments.models import FpPaymentRun, FpVendorQuery
from src.app.finance_pod.payments.router import router as payments_router
from src.app.finance_pod.reference.models import (
    FpAuthorityTier,
    FpBudget,
    FpCatalogueItem,
    FpCostCentre,
    FpGrant,
    FpVendor,
)
from src.app.finance_pod.reference.router import router as reference_router
from src.app.finance_pod.requests import service as requests_service
from src.app.finance_pod.requests.router import router as requests_router
from src.app.finance_pod.settings.router import router as settings_router
from src.app.finance_pod.sourcing.router import router as sourcing_router

# Finance Admin only (every route depends on FinanceAccessDep); the vendor portal is
# separate (onboarding.router.portal_router, no login)
router = APIRouter(prefix="/finance-pod", tags=["finance-pod"])
router.include_router(settings_router)
router.include_router(reference_router)
router.include_router(requests_router)
router.include_router(approvals_router)
router.include_router(sourcing_router)
router.include_router(onboarding_router)
router.include_router(orders_router)
router.include_router(invoices_router)
router.include_router(payments_router)
router.include_router(clients_router)
router.include_router(billing_router)


class OverviewOut(BaseModel):
    requests: dict[str, int]  # status -> count
    reference: dict[str, int]  # kind -> rows
    waiting_for_me: int  # request approval steps the viewer can decide now
    pos_waiting_for_me: int  # POs above the limit the viewer can approve now
    onboarding_open: int  # vendors being onboarded (not active or rejected)
    invoices: dict[str, int]  # Phase 3: status -> count
    exceptions_open: dict[str, int]  # Phase 3: open exceptions by status
    payment_runs: dict[str, int]  # payments: runs by status
    queries: dict[str, int]  # vendor queries by status
    client_applications: dict[str, int]  # receivables: applications by status
    credit_reviews_open: int  # the monitor's proposals waiting for the credit controller
    lab_submissions: dict[str, int]  # billing: submissions by status
    sales_invoices: dict[str, int]  # billing: client invoices by status


@router.get("/overview", response_model=OverviewOut)
async def overview(session: SessionDep, access: FinanceAccessDep) -> OverviewOut:
    """Where requests stand, and whether the reference data is loaded."""
    client_applications, credit_reviews_open = await clients_service.overview_counts(session)
    lab_submissions, sales_invoices = await billing_service.overview_counts(session)
    reference = {}
    for name, model in (
        ("cost_centres", FpCostCentre),
        ("grants", FpGrant),
        ("budgets", FpBudget),
        ("catalogue", FpCatalogueItem),
        ("vendors", FpVendor),
        ("authority", FpAuthorityTier),
    ):
        reference[name] = await session.scalar(select(func.count()).select_from(model)) or 0
    onboarding_open = await session.scalar(
        select(func.count())
        .select_from(FpOnboarding)
        .where(FpOnboarding.status.not_in([OnboardingStatus.ACTIVE, OnboardingStatus.REJECTED]))
    )
    return OverviewOut(
        requests=await requests_service.status_counts(session),
        reference=reference,
        waiting_for_me=len(await approvals_service.waiting_for(session, access.user)),
        pos_waiting_for_me=len(await orders_service.waiting_for(session, access.user)),
        onboarding_open=onboarding_open or 0,
        invoices={
            str(s): n
            for s, n in (
                await session.execute(
                    select(FpInvoice.status, func.count()).group_by(FpInvoice.status)
                )
            ).all()
        },
        exceptions_open={
            str(s): n
            for s, n in (
                await session.execute(
                    select(FpInvoiceException.status, func.count())
                    .where(FpInvoiceException.status != ExceptionStatus.RESOLVED)
                    .group_by(FpInvoiceException.status)
                )
            ).all()
        },
        payment_runs={
            str(s): n
            for s, n in (
                await session.execute(
                    select(FpPaymentRun.status, func.count()).group_by(FpPaymentRun.status)
                )
            ).all()
        },
        queries={
            str(s): n
            for s, n in (
                await session.execute(
                    select(FpVendorQuery.status, func.count()).group_by(FpVendorQuery.status)
                )
            ).all()
        },
        client_applications=client_applications,
        credit_reviews_open=credit_reviews_open,
        lab_submissions=lab_submissions,
        sales_invoices=sales_invoices,
    )


@router.get("/measures", response_model=measures_module.Measures)
async def measures(session: SessionDep, _: FinanceAccessDep) -> measures_module.Measures:
    """Request-to-PO cycle time, time per stage, rework and what's waiting where."""
    return await measures_module.measures(session)


@router.get("/measures/invoices")
async def invoice_measures(session: SessionDep, _: FinanceAccessDep) -> dict[str, object]:
    """Phase 3: first-pass match rate, exception ageing, duplicates stopped."""
    return await invoices_service.measures(session)


class DemoDataOut(BaseModel):
    loaded: list[str]
    skipped: list[str]  # already there
    notes: list[str]


@router.post("/demo-data", response_model=DemoDataOut)
async def load_demo_data(
    session: SessionDep, ctx: RequestContextDep, access: FinanceAccessDep
) -> DemoDataOut:
    """Load the demo data (any environment). Sections already there are left alone; no
    email is sent."""
    result = await demo.load(session, access.user, ctx)
    return DemoDataOut(loaded=result.loaded, skipped=result.skipped, notes=result.notes)


@router.get("/measures/clients")
async def client_measures(session: SessionDep, _: FinanceAccessDep) -> dict[str, object]:
    """Receivables: account set-up time and data errors."""
    return await clients_service.measures(session)


@router.get("/measures/billing")
async def billing_measures(session: SessionDep, _: FinanceAccessDep) -> dict[str, object]:
    """Receivables: billing accuracy and days to invoice."""
    return await billing_service.measures(session)
