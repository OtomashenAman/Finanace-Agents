"""Reading an imported reply in the background. If the AI can't read it reliably (not
configured, provider error, output that fails the checks) nothing is guessed: a person gets
a review task to read it and record what the customer said."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMError, LLMNotConfiguredError
from src.app.jobs.queue import JobContext, handler
from src.app.service_pod.common.ai import AiOutputRejectedError
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.models import LOCKED_STATUSES, PodCase, ReviewTaskKind
from src.app.service_pod.core.hooks import hooks_for
from src.app.service_pod.core.messaging.models import PodMessage
from src.app.service_pod.core.messaging.service import EXTRACT_JOB


@handler(EXTRACT_JOB)
async def extract_reply(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    message = await session.get(PodMessage, uuid.UUID(payload["message_id"]), with_for_update=True)
    if message is None or message.extraction_status != "pending":
        return
    case = await session.get(PodCase, message.case_id, with_for_update=True)
    assert case is not None  # noqa: S101 - cascade keeps them together
    read = hooks_for(case.workflow).extract_reply
    if read is None or case.status in LOCKED_STATUSES:
        message.extraction_status = "skipped"
        return

    try:
        await read(session, case, message, ctx.llm)
    except (LLMNotConfiguredError, LLMError, AiOutputRejectedError) as exc:
        reason = (
            "no AI provider is configured"
            if isinstance(exc, LLMNotConfiguredError)
            else str(exc)[:300] or type(exc).__name__
        )
        message.extraction_status = (
            "skipped" if isinstance(exc, LLMNotConfiguredError) else "failed"
        )
        message.extraction = {"error": reason}
        system.raise_task(
            session,
            case,
            ReviewTaskKind.AMBIGUITY,
            f"The reply from {message.from_email} wasn't read automatically ({reason}). Read it "
            "and record what the customer said; nothing was assumed.",
            subject=message.subject[:200] or None,
        )
        system.bump_case(session, case, "pod.reply_not_read", "reply needs reading by a person")
        return
    message.extraction_status = "done"
    system.bump_case(session, case, "pod.reply_read", f"read the reply from {message.from_email}")
