import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog import service as catalog
from src.app.agent_catalog.runs import service as runs
from src.app.agent_catalog.runs.models import RunPriority
from src.app.auth.models import User, UserRole
from src.app.core.config import get_settings
from src.app.data_sources import service as data_sources
from src.app.entities import service as entities
from src.app.monitoring import service as monitoring
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


async def get_summary(
    session: AsyncSession,
    user: User,
    period: str,
    entity_id: uuid.UUID | None = None,
    agent_key: str | None = None,
    priority: RunPriority | None = None,
) -> OverviewSummary:
    """Dashboard numbers, computed live from the feature modules on every request."""
    start, end = _month_bounds(period)
    entity = await entities.visible_entity(session, user, entity_id) if entity_id else None
    entity_label = f"{entity.code} · {entity.name}" if entity else ALL_ENTITIES
    stats = await runs.run_stats(
        session, user, start, end, entity_id, agent_key=agent_key, priority=priority
    )
    kpis = OverviewKpis(
        active_agents=await catalog.count_active_agents(session, user),
        runs_this_month=stats.runs_this_period,
        pending_review=stats.pending_review,
        high_priority=stats.high_priority,
    )
    controls = None
    if user.role == UserRole.FINANCE_ADMIN:
        controls = AdminControls(
            entity=entity_label,
            period_label=start.strftime("%B %Y"),
            review_sla_hours=get_settings().review_sla_hours,
            connector_health=await data_sources.health_summary(session),
            model_execution=await monitoring.health_line(session),
        )
    worklist = [
        WorklistItem(
            run_id=row.run_id,
            agent_key=row.agent_key,
            agent_name=row.agent_name,
            reference=row.reference,
            entity_code=row.entity_code,
            owner=row.owner,
            exceptions=row.exceptions,
            status=row.status.value,
            status_label=row.status_label,
            priority=row.priority.value,
            created_at=row.created_at,
        )
        for row in stats.worklist
    ]
    return OverviewSummary(
        period=period,
        entity=entity_label,
        entity_id=entity.id if entity else None,
        kpis=kpis,
        worklist=worklist,
        controls=controls,
    )
