"""Where a case stands, for worklists: whether its first email went out, whether the
customer replied, and how many review tasks are open. Each workflow turns this into the
step its case is on (its `stage` hook)."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.cases.models import PodCase, PodReviewTask, ReviewTaskStatus
from src.app.service_pod.core.messaging.models import Direction, MessageStatus, PodMessage


@dataclass(frozen=True)
class Progress:
    request_sent: bool
    replied: bool
    open_tasks: int


async def progress(session: AsyncSession, case: PodCase, request_purpose: str) -> Progress:
    sent = await session.scalar(
        select(func.count()).where(
            PodMessage.case_id == case.id,
            PodMessage.direction == Direction.OUTBOUND,
            PodMessage.purpose == request_purpose,
            PodMessage.status == MessageStatus.SENT,
        )
    )
    replied = await session.scalar(
        select(func.count()).where(
            PodMessage.case_id == case.id, PodMessage.direction == Direction.INBOUND
        )
    )
    open_tasks = await session.scalar(
        select(func.count()).where(
            PodReviewTask.case_id == case.id, PodReviewTask.status == ReviewTaskStatus.OPEN
        )
    )
    return Progress(request_sent=bool(sent), replied=bool(replied), open_tasks=open_tasks or 0)
