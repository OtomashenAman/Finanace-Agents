import uuid
from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from src.app.audit import integrity, service
from src.app.audit.labels import AuditCategory
from src.app.audit.schemas import AuditPage, ChainCheckOut
from src.app.auth.dependencies import AdminUser, CurrentUser
from src.app.common.clock import utcnow
from src.app.common.context import RequestContextDep
from src.app.core.config import get_settings
from src.app.core.db import SessionDep

# Read-only: the trail has no update or delete endpoints, for anyone
router = APIRouter(prefix="/audit-events", tags=["audit trail"])


def _filters(
    category: AuditCategory | None = None,
    actor_id: Annotated[uuid.UUID | None, Query(description="Finance Admin only")] = None,
    run: Annotated[str | None, Query(max_length=20, description="e.g. RUN-01006")] = None,
    since: date | None = None,
    until: Annotated[date | None, Query(description="Inclusive")] = None,
    failures_only: bool = False,
) -> service.AuditFilters:
    return service.AuditFilters(category, actor_id, run, since, until, failures_only)


Filters = Annotated[service.AuditFilters, Depends(_filters)]


@router.get("", response_model=AuditPage)
async def list_events(
    session: SessionDep, user: CurrentUser, filters: Filters, cursor: str | None = None
) -> AuditPage:
    """Newest first. Finance Admin: every event. User: their own actions, changes to their
    account and events on their own runs (without other people's IP or browser)."""
    return await service.list_events(session, user, filters, cursor)


@router.get("/export.csv", response_class=Response)
async def export_csv(
    session: SessionDep, admin: AdminUser, filters: Filters, ctx: RequestContextDep
) -> Response:
    """CSV for auditors (Finance Admin only, up to 10,000 rows). The export itself is audited."""
    body = await service.export_csv(session, admin, filters, ctx)
    filename = f"audit-trail-{utcnow():%Y%m%d-%H%M}.csv"
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/integrity", response_model=ChainCheckOut)
async def verify_integrity(session: SessionDep, _: AdminUser) -> ChainCheckOut:
    """Recompute the tamper-evident hash chain over every event (Finance Admin only)."""
    check = await integrity.verify(session)
    return ChainCheckOut(**asdict(check), retention_days=get_settings().audit_retention_days)
