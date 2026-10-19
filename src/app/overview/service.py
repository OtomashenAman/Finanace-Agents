from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog import service as catalog
from src.app.agent_catalog.runs import service as runs
from src.app.auth.models import User, UserRole
from src.app.core.config import get_settings
from src.app.overview.schemas import AdminControls, OverviewKpis, OverviewSummary, WorklistItem

ALL_ENTITIES = "All entities"


def _month_bounds(period: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(period, "%Y-%m").replace(tzinfo=UTC)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


async def get_summary(session: AsyncSession, user: User, period: str) -> OverviewSummary:
    """Dashboard numbers, computed live from the feature modules on every request."""
    start, end = _month_bounds(period)
    stats = await runs.run_stats(session, user, start, end)
    kpis = OverviewKpis(
        active_agents=await catalog.count_active_agents(session, user),
        runs_this_month=stats.runs_this_period,
        pending_review=stats.pending_review,
        high_priority=stats.high_priority,
    )
    controls = None
    if user.role == UserRole.FINANCE_ADMIN:
        controls = AdminControls(
            entity=ALL_ENTITIES,
            period_label=start.strftime("%B %Y"),
            review_sla_hours=get_settings().review_sla_hours,
            connector_health="Not configured",
            model_execution="Guarded",
        )
    worklist = [
        WorklistItem(
            run_id=row.run_id,
            agent_key=row.agent_key,
            agent_name=row.agent_name,
            reference=row.reference,
            status=row.status.value,
            status_label=row.status_label,
            priority=row.priority.value,
            created_at=row.created_at,
        )
        for row in stats.worklist
    ]
    return OverviewSummary(
        period=period, entity=ALL_ENTITIES, kpis=kpis, worklist=worklist, controls=controls
    )
