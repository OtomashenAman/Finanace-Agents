"""The Report months screen: which closed months each source can report, and the cases."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import get_settings
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.reporting.engine import prior_month
from src.app.service_pod.flows.reporting.schemas import (
    ReportCaseRow,
    ReportMonth,
    ReportMonths,
    ReportSource,
)

NEEDED = {"accounts", "gl_lines", "transactions", "balance_sheets", "close_status", "invoices"}


async def report_months(session: AsyncSession) -> ReportMonths:
    sources = []
    for summary in await snapshots.list_snapshots(session, None):
        if not set(summary.coverage) >= NEEDED:
            continue
        snap = await session.get(PodSnapshot, summary.id)
        assert snap is not None  # noqa: S101
        doc = snapshots.document(snap)
        with_pnl = {g.period for g in doc.gl_lines or []}
        closed = {c.period for c in doc.close_status or [] if c.status == "Closed"}
        sheets = {b.period for b in doc.balance_sheets or []}
        months = [
            ReportMonth(
                month=m,
                closed=m in closed,
                balance_sheet=m in sheets,
                prior_available=prior_month(m) in with_pnl,
            )
            for m in sorted(with_pnl, reverse=True)
        ]
        suggested = next(
            (m.month for m in months if m.closed and m.balance_sheet and m.prior_available), None
        )
        sources.append(
            ReportSource(
                snapshot=summary,
                months=months,
                business_units=sorted(
                    {g.business_unit for g in doc.gl_lines or [] if g.business_unit}
                ),
                suggested=suggested,
            )
        )
    cases = await session.scalars(
        select(PodCase)
        .where(PodCase.workflow == WorkflowKey.REPORTING)
        .order_by(PodCase.created_at.desc())
        .limit(50)
    )
    return ReportMonths(
        sources=sources,
        cases=[
            ReportCaseRow(
                id=str(c.id),
                reference=c.reference,
                title=c.title,
                status=c.status.value,
                month=str(c.selection.get("month", "")),
            )
            for c in cases
        ],
        internal_recipients=get_settings().pod_internal_recipients,
    )
