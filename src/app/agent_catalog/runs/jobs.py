"""Background work for runs: drafting the AI explanation after an analysis."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis, Calculation, Finding
from src.app.agent_catalog.models import Agent
from src.app.agent_catalog.registry import get_agent_definition
from src.app.agent_catalog.runs import narrative as narrative_service
from src.app.agent_catalog.runs.models import (
    ActionStatus,
    AgentRun,
    ExternalAction,
    NarrativeStatus,
    ReviewDecision,
    RunDocument,
    RunFlag,
    RunNarrative,
    RunReview,
    RunSourceSnapshot,
)
from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.data_sources import service as data_sources
from src.app.entities.models import LegalEntity
from src.app.jobs.models import Job, JobStatus
from src.app.jobs.queue import JobContext, RetryLater, handler

NARRATIVE_JOB = "run.narrative"
_SYSTEM = RequestContext(ip=None, user_agent="background worker")


def narrative_key(run: AgentRun) -> str:
    """One narrative job per analysis: re-analyzing queues a new one, retries don't."""
    assert run.analyzed_at is not None  # noqa: S101 - only queued after an analysis
    return f"narrative:{run.id}:{run.analyzed_at.isoformat()}"


def narrative_payload(run: AgentRun) -> dict[str, Any]:
    assert run.analyzed_at is not None  # noqa: S101
    return {"run_id": str(run.id), "analyzed_at": run.analyzed_at.isoformat()}


async def narrative_pending(session: AsyncSession, run: AgentRun) -> bool:
    if run.analyzed_at is None:
        return False
    status = await session.scalar(select(Job.status).where(Job.dedupe_key == narrative_key(run)))
    return status in (JobStatus.QUEUED, JobStatus.RUNNING)


@handler(NARRATIVE_JOB)
async def draft_narrative(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    run = await session.get(AgentRun, uuid.UUID(payload["run_id"]))
    if run is None or run.analyzed_at is None:
        return  # deleted, or reset by an edit
    if run.analyzed_at != datetime.fromisoformat(payload["analyzed_at"]):
        return  # superseded by a newer analysis (it has its own job)
    done = await session.scalar(
        select(RunNarrative.id).where(
            RunNarrative.run_id == run.id,
            RunNarrative.created_at >= run.analyzed_at,
            RunNarrative.status.in_([NarrativeStatus.OK, NarrativeStatus.NOT_CONFIGURED]),
        )
    )
    if done is not None:
        return  # already drafted (e.g. a retry after the worker died post-commit)

    agent = await session.get(Agent, run.agent_id)
    definition = get_agent_definition(agent.key) if agent else None
    if definition is None or definition.run_model is None or definition.input_schema is None:
        return
    detail = await session.get(definition.run_model, run.id)
    data = definition.input_schema.model_validate(
        {name: getattr(detail, name) for name in definition.input_schema.model_fields}
    )
    flags = await session.scalars(
        select(RunFlag).where(RunFlag.run_id == run.id).order_by(RunFlag.position)
    )
    analysis = Analysis(
        headline=run.headline or "",
        proposed_decision=run.proposed_decision or "",
        calculations=[
            Calculation(
                c["key"],
                c["label"],
                Decimal(c["value"]) if c.get("kind") == "money" and c["value"] else c["value"],
                c.get("kind", "money"),
            )
            for c in run.calculations
        ],
        findings=[Finding(f.code, f.severity, f.message, f.field) for f in flags],
    )
    documents = list(
        await session.scalars(
            select(RunDocument).where(RunDocument.run_id == run.id).order_by(RunDocument.created_at)
        )
    )
    entity = await session.get(LegalEntity, run.entity_id) if run.entity_id else None

    narrative = await narrative_service.generate(
        session,
        run,
        definition,
        data,
        analysis,
        documents,
        ctx.llm,
        entity.name if entity else None,
    )
    if narrative.status == NarrativeStatus.FAILED:
        # Keep the failed call on record (AI monitoring), then retry; after the last attempt
        # the job shows as failed in the queue, where an admin can run it again
        await session.commit()
        raise RetryLater(narrative.error or "LLM call failed")


# --- QuickBooks write-back --------------------------------------------------------------

WRITEBACK_JOB = "quickbooks.writeback"
BILL_NOTE = "quickbooks.bill_approval_note"


BILL_CREATE = "quickbooks.bill_create"


async def _approval_note(session: AsyncSession, run: AgentRun) -> tuple[str, str]:
    """The marker identifying the run and the line written to QuickBooks."""
    approvals = list(
        await session.execute(
            select(User.full_name, RunReview.created_at)
            .join(User, User.id == RunReview.reviewer_id)
            .where(RunReview.run_id == run.id, RunReview.decision == ReviewDecision.APPROVED)
            .order_by(RunReview.created_at)
        )
    )
    names = ", ".join(dict.fromkeys(name for name, _ in approvals)) or "Finance Admin"
    when = approvals[-1][1] if approvals else utcnow()
    marker = f"[FinanceACC] {run.reference}"
    line = (
        f"{marker} approved by {names} on {when:%Y-%m-%d} (result {(run.result_hash or '')[:12]})"
    )
    return marker, line


async def _perform(
    session: AsyncSession, action: ExternalAction, run: AgentRun, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Do the write; None when there's nothing left to write to."""
    marker, line = await _approval_note(session, run)
    if action.kind == BILL_CREATE:
        bill = payload["bill"]
        target = data_sources.BillTarget(
            **{**bill["target"], "source_id": uuid.UUID(bill["target"]["source_id"])}
        )
        return await data_sources.create_bill(
            session,
            target,
            doc_number=bill["doc_number"],
            amount=Decimal(bill["amount"]),
            note=line,
        )
    snapshot = await session.get(RunSourceSnapshot, action.run_id)
    if snapshot is None or snapshot.source_id is None:
        return None
    return await data_sources.stamp_bill(
        session, snapshot.source_id, str(snapshot.records["bill"]["external_id"]), marker, line
    )


@handler(WRITEBACK_JOB)
async def write_back(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    """Write an approved run to the preparer's QuickBooks: stamp the approval on the bill it
    was prefilled from, or create the bill for an invoice entered by hand."""
    action = await session.get(
        ExternalAction, uuid.UUID(payload["action_id"]), with_for_update=True
    )
    if action is None or action.status == ActionStatus.SUCCEEDED:
        return
    run = await session.get(AgentRun, action.run_id)
    try:
        receipt = await _perform(session, action, run, payload) if run else None
    except Exception as exc:
        action.error = f"{exc}"[:500]
        if ctx.final_attempt:
            action.status = ActionStatus.FAILED
            action.completed_at = utcnow()
            record_event(
                session,
                "run.writeback_failed",
                _SYSTEM,
                actor_id=action.requested_by,
                run=run.reference if run else None,
                error=action.error,
            )
        await session.commit()
        raise RetryLater(action.error) from exc
    if run is None or receipt is None:
        action.status = ActionStatus.FAILED
        action.error = "The run or its QuickBooks source is gone."
        return
    action.status = ActionStatus.SUCCEEDED
    action.receipt = receipt
    action.error = None
    action.completed_at = utcnow()
    record_event(
        session,
        "run.writeback_posted",
        _SYSTEM,
        actor_id=action.requested_by,
        run=run.reference,
        bill_id=receipt["bill_id"],
        already_present=receipt["already_present"],
        created=action.kind == BILL_CREATE and not receipt["already_present"],
    )
