from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog import service as catalog
from src.app.auth.models import User, UserRole
from src.app.core.config import get_settings
from src.app.overview.schemas import AdminControls, OverviewKpis, OverviewSummary

ALL_ENTITIES = "All entities"


async def get_summary(session: AsyncSession, user: User, period: str) -> OverviewSummary:
    """Dashboard numbers, computed live from the feature modules on every request."""
    kpis = OverviewKpis(
        active_agents=await catalog.count_active_agents(session, user),
        # Runs, review workload and the worklist come from the runs module (not built yet)
        runs_this_month=0,
        pending_review=0,
        high_priority=0,
    )
    controls = None
    if user.role == UserRole.FINANCE_ADMIN:
        controls = AdminControls(
            entity=ALL_ENTITIES,
            period_label=datetime.strptime(period, "%Y-%m").strftime("%B %Y"),  # noqa: DTZ007
            review_sla_hours=get_settings().review_sla_hours,
            connector_health="Not configured",
            model_execution="Guarded",
        )
    return OverviewSummary(
        period=period, entity=ALL_ENTITIES, kpis=kpis, worklist=[], controls=controls
    )
