import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.runs import service as runs
from src.app.approvals.schemas import ApprovalItem
from src.app.auth.models import User


async def list_approvals(
    session: AsyncSession, user: User, *, decided: bool, entity_id: uuid.UUID | None = None
) -> list[ApprovalItem]:
    """Computed from the runs feature on every request, like the overview."""
    rows = await runs.approval_rows(session, user, decided=decided, entity_id=entity_id)
    return [
        ApprovalItem(
            **row.summary.model_dump(), submitted_at=row.submitted_at, decided_at=row.decided_at
        )
        for row in rows
    ]
