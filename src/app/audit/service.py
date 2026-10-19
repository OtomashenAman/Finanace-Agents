import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.common.context import RequestContext


def record_event(
    session: AsyncSession,
    event_type: str,
    ctx: RequestContext,
    actor_id: uuid.UUID | None = None,
    **details: Any,
) -> None:
    """Add an audit event to the current transaction (caller commits)."""
    session.add(
        AuditEvent(
            event_type=event_type,
            actor_id=actor_id,
            ip=ctx.ip,
            user_agent=ctx.user_agent[:512] if ctx.user_agent else None,
            details=details,
        )
    )
