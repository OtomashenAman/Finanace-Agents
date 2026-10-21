import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.app.agent_catalog.agents.base import AnalysisContext, BaseAgent
from src.app.agent_catalog.agents.fields import draft_schema, form_fields
from src.app.agent_catalog.exceptions import AgentNotFoundError
from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.registry import get_agent_definition
from src.app.agent_catalog.runs import evidence
from src.app.agent_catalog.runs import jobs as run_jobs
from src.app.agent_catalog.runs.exceptions import (
    DocumentConflictError,
    DocumentNotFoundError,
    DocumentRejectedError,
    InvalidRunStateError,
    RunNotFoundError,
    RunPermissionError,
    WorkspaceUnavailableError,
)
from src.app.agent_catalog.runs.lifecycle import (
    REVIEW_OUTCOME,
    STATUS_LABELS,
    RunAction,
    ensure_allowed,
    is_allowed,
)
from src.app.agent_catalog.runs.models import (
    ActionStatus,
    AgentRun,
    AgentRunDetail,
    ExternalAction,
    FlagSeverity,
    ReviewDecision,
    RunDocument,
    RunFlag,
    RunNarrative,
    RunPriority,
    RunReview,
    RunSourceSnapshot,
    RunStatus,
)
from src.app.agent_catalog.runs.schemas import (
    BillPreview,
    CalculationOut,
    DocumentOut,
    DocumentText,
    FieldError,
    FlagOut,
    FormSpec,
    NarrativeOut,
    NarrativeOutput,
    Person,
    ReviewCreate,
    ReviewOut,
    RunActionOut,
    RunApproval,
    RunCreate,
    RunDetail,
    RunPermissions,
    RunSourceOut,
    RunSummary,
    SourceLink,
    WriteBackRequest,
)
from src.app.agent_catalog.service import ADMIN_CAPACITIES, visible_agent_ids
from src.app.audit import service as audit
from src.app.audit.schemas import AuditEventOut
from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.common.text_extraction.base import ExtractionError
from src.app.common.text_extraction.registry import extract_text
from src.app.core.config import get_settings
from src.app.core.llm.base import LLMProvider
from src.app.data_sources import service as data_sources
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource, SourceKind, SourceStatus
from src.app.entities import service as entities
from src.app.entities.schemas import EntityRef
from src.app.governance import service as governance
from src.app.jobs import queue as jobs

TEXT_PREVIEW_CHARS = 400


# --- access -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentAccess:
    agent: Agent
    definition: type[BaseAgent]
    user: User
    capacities: frozenset[AgentCapacity]

    @property
    def is_admin(self) -> bool:
        return self.user.role == UserRole.FINANCE_ADMIN

    @property
    def run_model(self) -> type[AgentRunDetail]:
        if self.definition.run_model is None:
            raise WorkspaceUnavailableError
        return self.definition.run_model

    @property
    def input_schema(self) -> type[BaseModel]:
        if self.definition.input_schema is None:
            raise WorkspaceUnavailableError
        return self.definition.input_schema


async def _access(session: AsyncSession, user: User, key: str) -> AgentAccess:
    """The agent as this user may see it: admins see all (with every capacity), others only
    assigned active agents."""
    agent = await session.scalar(select(Agent).where(Agent.key == key, Agent.retired_at.is_(None)))
    definition = get_agent_definition(key)
    if agent is None or definition is None:
        raise AgentNotFoundError
    if user.role == UserRole.FINANCE_ADMIN:
        capacities = ADMIN_CAPACITIES
    else:
        capacities = frozenset(
            await session.scalars(
                select(AgentAssignment.capacity).where(
                    AgentAssignment.user_id == user.id, AgentAssignment.agent_id == agent.id
                )
            )
        )
    access = AgentAccess(agent, definition, user, capacities)
    if not access.is_admin and (not capacities or not agent.is_active):
        raise AgentNotFoundError
    return access


def _require_owner(run: AgentRun, user: User) -> None:
    if run.preparer_id != user.id:
        raise RunPermissionError("Only the preparer of this run can change it.")


def _own_runs(query: Select[AgentRun], user: User) -> Select[AgentRun]:
    """Users only ever see their own runs, of the legal entities they work for; a Finance
    Admin sees (and reviews) everyone's."""
    if user.role == UserRole.FINANCE_ADMIN:
        return query
    return query.where(
        AgentRun.preparer_id == user.id,
        AgentRun.entity_id.is_(None)
        | AgentRun.entity_id.in_(entities.assigned_entity_ids(user.id)),
    )


def _in_entity(query: Select[AgentRun], entity_id: uuid.UUID | None) -> Select[AgentRun]:
    return query if entity_id is None else query.where(AgentRun.entity_id == entity_id)


async def _entities(session: AsyncSession, runs: list[AgentRun]) -> dict[uuid.UUID, EntityRef]:
    return await entities.refs(session, {r.entity_id for r in runs if r.entity_id})


async def _load(
    session: AsyncSession, access: AgentAccess, run_id: uuid.UUID, *, lock: bool = False
) -> tuple[AgentRun, AgentRunDetail]:
    query = _own_runs(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.agent_id == access.agent.id),
        access.user,
    )
    run = await session.scalar(query.with_for_update() if lock else query)
    if run is None:
        raise RunNotFoundError
    detail = await session.get(access.run_model, run.id)
    if detail is None:  # pragma: no cover - created together with the run
        raise RunNotFoundError
    return run, detail


def _input_values(access: AgentAccess, detail: AgentRunDetail) -> dict[str, Any]:
    return {name: getattr(detail, name) for name in access.input_schema.model_fields}


def _jsonable(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


async def _reset_analysis(session: AsyncSession, run: AgentRun) -> None:
    """Input or evidence changed: the previous analysis no longer applies."""
    run.status = RunStatus.DRAFT
    run.headline = None
    run.proposed_decision = None
    run.calculations = []
    run.validation_errors = None
    run.priority = RunPriority.NORMAL
    run.analyzed_at = None
    run.result_hash = None
    await session.execute(delete(RunFlag).where(RunFlag.run_id == run.id))


# --- read -------------------------------------------------------------------------------


async def get_form(session: AsyncSession, user: User, key: str) -> FormSpec:
    access = await _access(session, user, key)
    return FormSpec(
        agent_key=key,
        fields=form_fields(access.input_schema),
        controls=list(access.definition.controls),
    )


async def _people(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Person]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return {uid: Person(id=uid, full_name=name) for uid, name in rows}


async def _business_refs(session: AsyncSession, runs: list[AgentRun]) -> dict[uuid.UUID, str]:
    """The agent-specific reference (e.g. invoice number) for each run."""
    refs: dict[uuid.UUID, str] = {}
    by_agent: dict[uuid.UUID, list[uuid.UUID]] = {}
    for run in runs:
        by_agent.setdefault(run.agent_id, []).append(run.id)
    agents = {
        a.id: a.key for a in await session.scalars(select(Agent).where(Agent.id.in_(by_agent)))
    }
    for agent_id, run_ids in by_agent.items():
        definition = get_agent_definition(agents[agent_id])
        if not definition or not definition.run_model or not definition.reference_field:
            continue
        model = definition.run_model
        column = getattr(model, definition.reference_field)
        rows = await session.execute(
            select(model.run_id, column).where(model.run_id.in_(run_ids), column.is_not(None))
        )
        refs.update({run_id: str(value) for run_id, value in rows})
    return refs


def _summary(
    run: AgentRun,
    agent: Agent,
    preparer: Person,
    business_ref: str | None,
    entity_refs: dict[uuid.UUID, EntityRef],
) -> dict[str, Any]:
    return {
        "id": run.id,
        "reference": run.reference,
        "agent_key": agent.key,
        "agent_name": agent.short_name,
        "business_reference": business_ref,
        "entity": entity_refs.get(run.entity_id) if run.entity_id else None,
        "status": run.status,
        "status_label": STATUS_LABELS[run.status],
        "priority": run.priority,
        "headline": run.headline,
        "preparer": preparer,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


async def list_runs(
    session: AsyncSession, user: User, key: str, entity_id: uuid.UUID | None = None
) -> list[RunSummary]:
    access = await _access(session, user, key)
    query = _own_runs(select(AgentRun).where(AgentRun.agent_id == access.agent.id), user)
    runs = list(
        await session.scalars(
            _in_entity(query, entity_id).order_by(AgentRun.run_number.desc()).limit(50)
        )
    )
    people = await _people(session, {r.preparer_id for r in runs})
    refs = await _business_refs(session, runs)
    ents = await _entities(session, runs)
    return [
        RunSummary(**_summary(r, access.agent, people[r.preparer_id], refs.get(r.id), ents))
        for r in runs
    ]


async def get_run(session: AsyncSession, user: User, key: str, run_id: uuid.UUID) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id)
    return await _detail(session, access, run, detail)


def _round_approvals(run: AgentRun, reviews: list[RunReview]) -> list[RunReview]:
    """Approvals given since the run was (re)submitted: a resubmission starts over."""
    return [
        r
        for r in reviews
        if r.decision == ReviewDecision.APPROVED
        and run.submitted_at is not None
        and r.created_at >= run.submitted_at
    ]


def _approver_ids(run: AgentRun) -> set[uuid.UUID]:
    ids = (run.approval_rule or {}).get("approver_ids", [])
    return {uuid.UUID(i) for i in ids}


def _approved_by(run: AgentRun, reviews: list[RunReview]) -> set[uuid.UUID]:
    """People whose approval this round already counts (in person or through a delegate)."""
    people: set[uuid.UUID] = set()
    for r in _round_approvals(run, reviews):
        people.add(r.reviewer_id)
        if r.on_behalf_of_id:
            people.add(r.on_behalf_of_id)
    return people


async def _acting_for(
    session: AsyncSession, user: User, run: AgentRun, reviews: list[RunReview]
) -> tuple[bool, uuid.UUID | None]:
    """(may decide as an approver, named approver they stand in for if any)."""
    approvers = _approver_ids(run)
    if not approvers or user.id in approvers:
        return True, None
    covering = sorted(
        (approvers & await governance.delegators_of(session, user.id)) - _approved_by(run, reviews)
    )
    return (True, covering[0]) if covering else (False, None)


async def _review_blocked(
    session: AsyncSession, user: User, run: AgentRun, reviews: list[RunReview]
) -> str | None:
    """Why this user may not decide on the run now (None: they may)."""
    if user.role != UserRole.FINANCE_ADMIN:
        return "Only a Finance Admin can approve runs."
    if user.id in _approved_by(run, reviews):
        return "You already approved this run: another approver must give the next approval."
    allowed, _ = await _acting_for(session, user, run, reviews)
    if not allowed:
        return (
            "Only the approvers set for this amount in the approval matrix "
            "(or their delegates) can decide."
        )
    if run.preparer_id == user.id and not await governance.allow_self_approval(session):
        return "You can't review a run you prepared (segregation of duties)."
    return None


ACTION_LABELS = {
    run_jobs.BILL_NOTE: "Approval noted on the QuickBooks bill",
    run_jobs.BILL_CREATE: "Bill created in QuickBooks",
}


WRITE_BACK_MODES: dict[str, Literal["note", "create_bill"]] = {
    run_jobs.BILL_NOTE: "note",
    run_jobs.BILL_CREATE: "create_bill",
}


@dataclass(frozen=True)
class WriteBackOption:
    kind: str | None  # run_jobs.BILL_NOTE or BILL_CREATE; None: not for this run
    blocked: str | None  # why it can't be asked for now


def _bill_preview(definition: type[BaseAgent], detail: AgentRunDetail) -> BillPreview | None:
    if definition.bill_fields is None:
        return None
    vendor_field, number_field, amount_field = definition.bill_fields
    hint = getattr(detail, definition.bill_account_field) if definition.bill_account_field else None
    return BillPreview(
        vendor=str(getattr(detail, vendor_field)),
        doc_number=str(getattr(detail, number_field)),
        amount=str(getattr(detail, amount_field)),
        account_hint=str(hint) if hint else None,
    )


async def _write_back_option(
    session: AsyncSession, access: AgentAccess, run: AgentRun, actions: list[ExternalAction]
) -> WriteBackOption:
    """How an approved run goes back to the preparer's QuickBooks, if it can."""
    if run.preparer_id != access.user.id or run.status != RunStatus.APPROVED:
        return WriteBackOption(None, None)
    snapshot = await session.get(RunSourceSnapshot, run.id)
    if snapshot and snapshot.source_kind == "quickbooks" and snapshot.record_type == "bill":
        kind = run_jobs.BILL_NOTE
        if snapshot.source_id is None:
            return WriteBackOption(kind, "The QuickBooks connection was removed.")
    elif access.definition.bill_fields is not None:
        kind = run_jobs.BILL_CREATE
        connected = await session.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(
                DataSource.owner_id == access.user.id,
                DataSource.kind == SourceKind.QUICKBOOKS,
                DataSource.status == SourceStatus.CONNECTED,
            )
        )
        if not connected:
            return WriteBackOption(
                kind, "Connect QuickBooks on Data Sources to create this bill there."
            )
    else:
        return WriteBackOption(None, None)
    if any(a.kind == kind and a.status != ActionStatus.FAILED for a in actions):
        return WriteBackOption(kind, "Already written back.")
    return WriteBackOption(kind, None)


async def write_back(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    body: WriteBackRequest | None,
    ctx: RequestContext,
    llm: LLMProvider,
) -> RunDetail:
    """Queue the QuickBooks write-back (once per run; a failed one can be asked for again)."""
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    actions = list(
        await session.scalars(select(ExternalAction).where(ExternalAction.run_id == run.id))
    )
    option = await _write_back_option(session, access, run, actions)
    if option.kind is None:
        raise RunPermissionError(
            "Only the preparer of an approved run can write it back to QuickBooks."
        )
    if option.blocked:
        raise RunPermissionError(option.blocked)
    payload: dict[str, Any] = {}
    if option.kind == run_jobs.BILL_CREATE:
        if body is None:
            raise RunPermissionError("Pick the QuickBooks company and the expense account.")
        assert access.definition.bill_fields is not None  # noqa: S101 - BILL_CREATE needs them
        vendor_field, number_field, amount_field = access.definition.bill_fields
        target = await data_sources.bill_target(
            session, user, body.source_id, getattr(detail, vendor_field), body.account_id
        )
        payload["bill"] = {
            "target": {**asdict(target), "source_id": str(target.source_id)},
            "doc_number": str(getattr(detail, number_field)),
            "amount": str(getattr(detail, amount_field)),
        }
    action = next((a for a in actions if a.kind == option.kind), None)
    if action is None:
        action = ExternalAction(
            run_id=run.id, kind=option.kind, status=ActionStatus.QUEUED, requested_by=user.id
        )
        session.add(action)
        await session.flush()
    else:  # a failed attempt, asked for again
        action.status = ActionStatus.QUEUED
        action.error = None
        action.requested_by = user.id
    job = await jobs.enqueue(
        session,
        run_jobs.WRITEBACK_JOB,
        {"action_id": str(action.id), **payload},
        dedupe_key=f"writeback:{action.id}:{utcnow().timestamp()}",
        max_attempts=4,
    )
    record_event(
        session,
        "run.writeback_requested",
        ctx,
        actor_id=user.id,
        run=run.reference,
        action=option.kind,
    )
    await session.commit()
    await jobs.dispatch(session, job, llm)
    await session.refresh(run)
    return await _detail(session, access, run, detail)


async def evidence_pack(
    session: AsyncSession, user: User, key: str, run_id: uuid.UUID, ctx: RequestContext
) -> tuple[bytes, str]:
    """ZIP for auditors (preparer or Finance Admin). Returns (bytes, filename); audited."""
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id)
    out = await _detail(session, access, run, detail)
    documents = [
        (d.filename, d.sha256, d.extracted_text)
        for d in await session.scalars(
            select(RunDocument).where(RunDocument.run_id == run.id).order_by(RunDocument.created_at)
        )
    ]
    timeline = await audit.run_timeline(session, user, run.reference)
    data = evidence.build(out, documents, timeline, user.email)
    record_event(
        session,
        "run.evidence_exported",
        ctx,
        actor_id=user.id,
        run=run.reference,
        sha256=hashlib.sha256(data).hexdigest(),
    )
    await session.commit()
    return data, f"{run.reference}-evidence.zip"


async def get_timeline(
    session: AsyncSession, user: User, key: str, run_id: uuid.UUID
) -> list[AuditEventOut]:
    """The run's audit events, for whoever may open the run (its preparer, or an admin)."""
    access = await _access(session, user, key)
    run, _ = await _load(session, access, run_id)
    return await audit.run_timeline(session, user, run.reference)


async def _detail(
    session: AsyncSession, access: AgentAccess, run: AgentRun, detail: AgentRunDetail
) -> RunDetail:
    flags = await session.scalars(
        select(RunFlag).where(RunFlag.run_id == run.id).order_by(RunFlag.position)
    )
    documents = list(
        await session.scalars(
            select(RunDocument).where(RunDocument.run_id == run.id).order_by(RunDocument.created_at)
        )
    )
    reviews = list(
        await session.scalars(
            select(RunReview).where(RunReview.run_id == run.id).order_by(RunReview.created_at)
        )
    )
    narrative = None
    if run.analyzed_at is not None:
        narrative = await session.scalar(
            select(RunNarrative)
            .where(RunNarrative.run_id == run.id, RunNarrative.created_at >= run.analyzed_at)
            .order_by(RunNarrative.created_at.desc())
            .limit(1)
        )
    people = await _people(
        session,
        {run.preparer_id}
        | {r.reviewer_id for r in reviews}
        | {r.on_behalf_of_id for r in reviews if r.on_behalf_of_id},
    )
    refs = await _business_refs(session, [run])
    ents = await _entities(session, [run])
    snapshot = await session.get(RunSourceSnapshot, run.id)

    user = access.user
    is_owner = run.preparer_id == user.id
    pending = is_allowed(run.status, RunAction.REVIEW)
    blocked = await _review_blocked(session, user, run, reviews) if pending else None
    drafting = await run_jobs.narrative_pending(session, run)
    actions = list(
        await session.scalars(
            select(ExternalAction)
            .where(ExternalAction.run_id == run.id)
            .order_by(ExternalAction.created_at)
        )
    )
    write_back = await _write_back_option(session, access, run, actions)
    permissions = RunPermissions(
        can_edit=is_owner and is_allowed(run.status, RunAction.EDIT),
        can_analyze=is_owner and is_allowed(run.status, RunAction.ANALYZE),
        # The AI explanation is part of what gets approved (result hash): wait for it
        can_submit=is_owner and is_allowed(run.status, RunAction.SUBMIT) and not drafting,
        can_review=pending and blocked is None,
        can_delete=is_owner and is_allowed(run.status, RunAction.DELETE),
        review_blocked_reason=blocked,
        can_write_back=write_back.kind is not None and write_back.blocked is None,
        write_back=WRITE_BACK_MODES.get(write_back.kind or ""),
        write_back_blocked_reason=write_back.blocked,
        bill=_bill_preview(access.definition, detail)
        if write_back.kind == run_jobs.BILL_CREATE
        else None,
    )
    approval = None
    if run.submitted_at is not None:
        round_approvals = _round_approvals(run, reviews)
        approver_ids = _approver_ids(run)
        names = await _people(session, approver_ids | {r.reviewer_id for r in round_approvals})
        rule = run.approval_rule or {}
        approval = RunApproval(
            required=run.required_approvals,
            received=len(round_approvals),
            approvers=[names[i] for i in approver_ids if i in names],
            amount=rule.get("amount"),
            tier_min_amount=rule.get("min_amount"),
            approved_by=[names[r.reviewer_id] for r in round_approvals],
        )
    return RunDetail(
        **_summary(run, access.agent, people[run.preparer_id], refs.get(run.id), ents),
        input={k: _jsonable(v) for k, v in _input_values(access, detail).items()},
        validation_errors=(
            [FieldError(**e) for e in run.validation_errors] if run.validation_errors else None
        ),
        proposed_decision=run.proposed_decision,
        policy_version=run.policy_version,
        policy_values=run.policy_values,
        approval=approval,
        narrative_pending=drafting,
        actions=[
            RunActionOut(
                kind=a.kind,
                label=ACTION_LABELS.get(a.kind, a.kind),
                status=a.status.value,
                receipt=a.receipt,
                error=a.error,
                created_at=a.created_at,
                completed_at=a.completed_at,
            )
            for a in actions
        ],
        calculations=[CalculationOut(**c) for c in run.calculations],
        flags=[
            FlagOut(code=f.code, severity=f.severity, message=f.message, field=f.field)
            for f in flags
        ],
        controls=list(access.definition.controls),
        reviewer_label=access.agent.reviewer,
        documents=[
            DocumentOut(
                id=d.id,
                filename=d.filename,
                content_type=d.content_type,
                size_bytes=d.size_bytes,
                sha256=d.sha256,
                extractor=d.extractor,
                page_count=d.page_count,
                char_count=d.char_count,
                truncated=d.truncated,
                warnings=d.warnings,
                text_preview=d.extracted_text[:TEXT_PREVIEW_CHARS],
                created_at=d.created_at,
            )
            for d in documents
        ],
        narrative=(
            NarrativeOut(
                status=narrative.status,
                provider=narrative.provider,
                model=narrative.model,
                prompt_version=narrative.prompt_version,
                output=NarrativeOutput(**narrative.output) if narrative.output else None,
                guard_warnings=narrative.guard_warnings,
                error=narrative.error,
                input_tokens=narrative.input_tokens,
                output_tokens=narrative.output_tokens,
                latency_ms=narrative.latency_ms,
                created_at=narrative.created_at,
            )
            if narrative
            else None
        ),
        reviews=[
            ReviewOut(
                id=r.id,
                reviewer=people[r.reviewer_id],
                on_behalf_of=people.get(r.on_behalf_of_id) if r.on_behalf_of_id else None,
                decision=r.decision,
                comment=r.comment,
                result_hash=r.result_hash,
                created_at=r.created_at,
            )
            for r in reviews
        ],
        source=(
            RunSourceOut(
                source_id=snapshot.source_id,
                source_kind=snapshot.source_kind,
                source_name=snapshot.source_name,
                record_type=snapshot.record_type,
                record_reference=snapshot.record_reference,
                records=snapshot.records,
                source_synced_at=snapshot.source_synced_at,
                captured_at=snapshot.created_at,
            )
            if snapshot
            else None
        ),
        result_hash=run.result_hash,
        analyzed_at=run.analyzed_at,
        submitted_at=run.submitted_at,
        decided_at=run.decided_at,
        permissions=permissions,
    )


async def get_document_text(
    session: AsyncSession, user: User, key: str, run_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentText:
    access = await _access(session, user, key)
    run, _ = await _load(session, access, run_id)
    document = await session.scalar(
        select(RunDocument).where(RunDocument.id == document_id, RunDocument.run_id == run.id)
    )
    if document is None:
        raise DocumentNotFoundError
    return DocumentText(
        id=document.id, filename=document.filename, extracted_text=document.extracted_text
    )


# --- preparer actions -------------------------------------------------------------------


async def create_run(
    session: AsyncSession,
    user: User,
    key: str,
    body: RunCreate,
    ctx: RequestContext,
    idempotency_key: str | None = None,
) -> tuple[RunDetail, bool]:
    """Returns (run, created). The same Idempotency-Key returns the run it created before."""
    access = await _access(session, user, key)
    if idempotency_key:
        existing = await session.scalar(
            select(AgentRun).where(
                AgentRun.preparer_id == user.id,
                AgentRun.idempotency_key == idempotency_key,
                AgentRun.agent_id == access.agent.id,
            )
        )
        if existing is not None:
            detail = await session.get(access.run_model, existing.id)
            assert detail is not None  # noqa: S101 - created together
            return await _detail(session, access, existing, detail), False
    if not access.definition.has_workspace():
        raise WorkspaceUnavailableError
    if not access.agent.is_active:
        raise WorkspaceUnavailableError("This agent is disabled.")
    if AgentCapacity.PREPARER not in access.capacities:
        raise RunPermissionError("Only users assigned as preparer for this agent can start a run.")

    entity = await entities.entity_for_new_run(session, user, body.entity_id)
    run = AgentRun(
        agent_id=access.agent.id,
        preparer_id=user.id,
        entity_id=entity.id if entity else None,
        idempotency_key=idempotency_key,
        status=RunStatus.DRAFT,
        priority=RunPriority.NORMAL,
        policy_version=access.definition.policy_version,
        calculations=[],
    )
    session.add(run)
    await session.flush()
    detail = access.run_model()
    detail.run_id = run.id
    session.add(detail)
    record_event(
        session,
        "run.created",
        ctx,
        actor_id=user.id,
        run=run.reference,
        agent=key,
        entity=entity.code if entity else None,
    )
    await session.commit()
    return await _detail(session, access, run, detail), True


async def update_input(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    values: dict[str, Any],
) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.EDIT)
    try:
        draft = draft_schema(access.input_schema).model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**e, "loc": ("body", "values", *e["loc"])} for e in exc.errors(include_url=False)]
        ) from exc

    for name, value in draft.model_dump().items():
        setattr(detail, name, value)
    if run.status != RunStatus.DRAFT:
        await _reset_analysis(session, run)
    await session.commit()
    return await _detail(session, access, run, detail)


async def link_source(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    body: SourceLink,
    ctx: RequestContext,
) -> RunDetail:
    """Prefill the input from one of the preparer's own data source records and freeze a
    snapshot of them for the reviewer. Fields the source doesn't know are left as they are."""
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.EDIT)
    record_type = access.definition.source_record_type
    if record_type is None:
        raise WorkspaceUnavailableError("This agent can't be prefilled from a data source.")

    source, record = await data_sources.owned_record(
        session, user, body.source_id, record_type, body.record_id
    )
    prefill = await access.definition.prefill(
        record, source, FinanceData(session, user.id, source.id)
    )
    values = {**_input_values(access, detail), **prefill.values}
    try:
        draft = draft_schema(access.input_schema).model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**e, "loc": ("body", "values", *e["loc"])} for e in exc.errors(include_url=False)]
        ) from exc
    for name, value in draft.model_dump().items():
        setattr(detail, name, value)

    records = {
        record_type.value: record.model_dump(mode="json"),
        **{name: r.model_dump(mode="json") for name, r in prefill.related.items()},
    }
    snapshot = await session.get(RunSourceSnapshot, run.id)
    if snapshot is None:
        snapshot = RunSourceSnapshot(run_id=run.id)
        session.add(snapshot)
    snapshot.source_id = source.id
    snapshot.source_kind = source.kind.value
    snapshot.source_name = source.name
    snapshot.record_type = record_type.value
    snapshot.record_reference = record.reference
    snapshot.records = records
    snapshot.source_synced_at = source.last_synced_at
    snapshot.created_at = utcnow()

    if run.status != RunStatus.DRAFT:
        await _reset_analysis(session, run)
    record_event(
        session,
        "run.source_linked",
        ctx,
        actor_id=user.id,
        run=run.reference,
        source_id=str(source.id),
        record=f"{record_type.value}:{record.external_id}",
    )
    await session.commit()
    return await _detail(session, access, run, detail)


async def unlink_source(
    session: AsyncSession, user: User, key: str, run_id: uuid.UUID, ctx: RequestContext
) -> RunDetail:
    """Drop the snapshot; the input values stay for the preparer to edit."""
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.EDIT)
    snapshot = await session.get(RunSourceSnapshot, run.id)
    if snapshot is not None:
        await session.delete(snapshot)
        if run.status != RunStatus.DRAFT:
            await _reset_analysis(session, run)
        record_event(session, "run.source_unlinked", ctx, actor_id=user.id, run=run.reference)
        await session.commit()
    return await _detail(session, access, run, detail)


async def delete_run(
    session: AsyncSession, user: User, key: str, run_id: uuid.UUID, ctx: RequestContext
) -> None:
    access = await _access(session, user, key)
    run, _ = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.DELETE)
    record_event(session, "run.deleted", ctx, actor_id=user.id, run=run.reference, agent=key)
    await session.delete(run)
    await session.commit()


async def analyze_run(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    ctx: RequestContext,
    llm: LLMProvider,
) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.ANALYZE)

    try:
        data = access.input_schema.model_validate(_input_values(access, detail))
    except ValidationError as exc:
        await _reset_analysis(session, run)
        run.status = RunStatus.VALIDATION_FAILED
        run.validation_errors = [
            {"field": str(e["loc"][0]) if e["loc"] else None, "message": e["msg"]}
            for e in exc.errors(include_url=False)
        ]
        record_event(session, "run.validation_failed", ctx, actor_id=user.id, run=run.reference)
        await session.commit()
        return await _detail(session, access, run, detail)

    documents = list(
        await session.scalars(
            select(RunDocument).where(RunDocument.run_id == run.id).order_by(RunDocument.created_at)
        )
    )
    snapshot = await session.get(RunSourceSnapshot, run.id)
    finance_data = FinanceData(session, run.preparer_id, snapshot.source_id if snapshot else None)
    policy = await governance.policy_in_force(session, access.definition)
    analysis = await access.definition.analyze(
        data,
        AnalysisContext(
            session=session,
            run=run,
            document_count=len(documents),
            data=finance_data,
            policy=policy.values if access.definition.policy_schema else None,
        ),
    )

    await session.execute(delete(RunFlag).where(RunFlag.run_id == run.id))
    for position, finding in enumerate(analysis.findings):
        session.add(
            RunFlag(
                run_id=run.id,
                position=position,
                code=finding.code,
                severity=finding.severity,
                message=finding.message,
                field=finding.field,
            )
        )
    for name, value in analysis.computed.items():
        setattr(detail, name, value)
    run.calculations = [
        {"key": c.key, "label": c.label, "value": _jsonable(c.value), "kind": c.kind}
        for c in analysis.calculations
    ]
    run.headline = analysis.headline
    run.proposed_decision = analysis.proposed_decision
    run.priority = analysis.priority
    run.validation_errors = None
    run.policy_version = policy.label
    run.policy_values = (
        policy.values.model_dump(mode="json") if access.definition.policy_schema else None
    )
    run.status = RunStatus.ANALYZED
    run.analyzed_at = utcnow()
    record_event(
        session,
        "run.analyzed",
        ctx,
        actor_id=user.id,
        run=run.reference,
        headline=analysis.headline,
        priority=analysis.priority.value,
    )
    await session.commit()

    # The AI explanation is drafted in the background (a worker), never holding this request
    job = await jobs.enqueue(
        session,
        run_jobs.NARRATIVE_JOB,
        run_jobs.narrative_payload(run),
        dedupe_key=run_jobs.narrative_key(run),
    )
    await session.commit()
    await jobs.dispatch(session, job, llm)
    return await _detail(session, access, run, detail)


async def add_document(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    filename: str,
    data: bytes,
    ctx: RequestContext,
) -> RunDetail:
    """Extract text from an upload and keep only the text + SHA-256 (never the file)."""
    settings = get_settings()
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.EDIT)

    count = await session.scalar(
        select(func.count()).select_from(RunDocument).where(RunDocument.run_id == run.id)
    )
    if (count or 0) >= settings.upload_max_files_per_run:
        raise DocumentConflictError(
            f"A run can have at most {settings.upload_max_files_per_run} documents."
        )
    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = await session.scalar(
        select(RunDocument.filename).where(
            RunDocument.run_id == run.id, RunDocument.sha256 == sha256
        )
    )
    if duplicate is not None:
        raise DocumentConflictError(f"This file is already attached as '{duplicate}'.")

    try:
        extracted = await run_in_threadpool(extract_text, data, filename)
    except ExtractionError as exc:
        raise DocumentRejectedError(str(exc)) from exc

    text = extracted.text
    truncated = len(text) > settings.extracted_text_max_chars
    if truncated:
        text = text[: settings.extracted_text_max_chars]
        extracted.warnings.append(
            f"Text was cut to the first {settings.extracted_text_max_chars:,} characters"
        )
    session.add(
        RunDocument(
            run_id=run.id,
            filename=filename[:255],
            content_type=extracted.content_type,
            size_bytes=len(data),
            sha256=sha256,
            extractor=extracted.extractor,
            page_count=extracted.page_count,
            char_count=len(text),
            truncated=truncated,
            warnings=extracted.warnings,
            extracted_text=text,
            uploaded_by=user.id,
        )
    )
    if run.status != RunStatus.DRAFT:
        await _reset_analysis(session, run)
    record_event(
        session,
        "run.document_added",
        ctx,
        actor_id=user.id,
        run=run.reference,
        filename=filename[:255],
        sha256=sha256,
    )
    await session.commit()
    return await _detail(session, access, run, detail)


async def remove_document(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: RequestContext,
) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.EDIT)
    document = await session.scalar(
        select(RunDocument).where(RunDocument.id == document_id, RunDocument.run_id == run.id)
    )
    if document is None:
        raise DocumentNotFoundError
    record_event(
        session,
        "run.document_removed",
        ctx,
        actor_id=user.id,
        run=run.reference,
        filename=document.filename,
        sha256=document.sha256,
    )
    await session.delete(document)
    if run.status != RunStatus.DRAFT:
        await _reset_analysis(session, run)
    await session.commit()
    return await _detail(session, access, run, detail)


def _result_hash(run: AgentRun, detail: RunDetail) -> str:
    """Fingerprint of exactly what the reviewer is asked to approve."""
    canonical = {
        "run": run.reference,
        "agent": detail.agent_key,
        "policy_version": run.policy_version,
        "policy": run.policy_values,
        "input": detail.input,
        "calculations": [c.model_dump() for c in detail.calculations],
        "flags": [f.model_dump(mode="json") for f in detail.flags],
        "documents": sorted(d.sha256 for d in detail.documents),
        "source": detail.source.records if detail.source else None,
        "narrative": detail.narrative.output.model_dump()
        if detail.narrative and detail.narrative.output
        else None,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


async def submit_run(
    session: AsyncSession, user: User, key: str, run_id: uuid.UUID, ctx: RequestContext
) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    _require_owner(run, user)
    ensure_allowed(run.status, RunAction.SUBMIT)
    if await run_jobs.narrative_pending(session, run):
        raise InvalidRunStateError(
            "The AI explanation is still being drafted. Submit when it's ready."
        )

    run.result_hash = _result_hash(run, await _detail(session, access, run, detail))
    data = access.input_schema.model_validate(_input_values(access, detail))
    route = await governance.route_for(session, key, access.definition.approval_amount(data))
    run.required_approvals = route.required
    run.approval_rule = route.snapshot()
    run.status = RunStatus.PENDING_APPROVAL
    run.submitted_at = utcnow()
    record_event(
        session,
        "run.submitted",
        ctx,
        actor_id=user.id,
        run=run.reference,
        result_hash=run.result_hash,
        approvals_required=route.required,
    )
    await session.commit()
    return await _detail(session, access, run, detail)


# --- reviewer actions -------------------------------------------------------------------


async def review_run(
    session: AsyncSession,
    user: User,
    key: str,
    run_id: uuid.UUID,
    body: ReviewCreate,
    ctx: RequestContext,
) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id, lock=True)
    reviews = list(await session.scalars(select(RunReview).where(RunReview.run_id == run.id)))
    if not access.is_admin:
        raise RunPermissionError("Only a Finance Admin can approve runs.")
    ensure_allowed(run.status, RunAction.REVIEW)
    if blocked := await _review_blocked(session, user, run, reviews):
        raise RunPermissionError(blocked)
    self_review = run.preparer_id == user.id  # only when the setting allows it; audited
    _, on_behalf_of = await _acting_for(session, user, run, reviews)
    assert run.result_hash is not None  # noqa: S101 - set on submit

    session.add(
        RunReview(
            run_id=run.id,
            reviewer_id=user.id,
            decision=body.decision,
            comment=body.comment.strip(),
            result_hash=run.result_hash,
            on_behalf_of_id=on_behalf_of,
        )
    )
    approvals = len(_round_approvals(run, reviews)) + 1
    if body.decision == ReviewDecision.APPROVED and approvals < run.required_approvals:
        # More approvals needed (approval matrix): stays pending for the next approver
        event = "run.approval_recorded"
    else:
        run.status = REVIEW_OUTCOME[body.decision]
        run.decided_at = utcnow() if run.status != RunStatus.CHANGES_REQUESTED else None
        event = f"run.{body.decision.value}"
    record_event(
        session,
        event,
        ctx,
        actor_id=user.id,
        run=run.reference,
        result_hash=run.result_hash,
        self_review=self_review,
        on_behalf_of=(await _people(session, {on_behalf_of}))[on_behalf_of].full_name
        if on_behalf_of
        else None,
        approvals=f"{approvals}/{run.required_approvals}"
        if body.decision == ReviewDecision.APPROVED
        else None,
    )
    await session.commit()
    return await _detail(session, access, run, detail)


# --- approvals --------------------------------------------------------------------------

DECIDED_STATUSES = (RunStatus.APPROVED, RunStatus.REJECTED, RunStatus.CHANGES_REQUESTED)


@dataclass(frozen=True)
class ApprovalRow:
    summary: RunSummary
    submitted_at: datetime | None
    decided_at: datetime | None


async def approval_rows(
    session: AsyncSession,
    user: User,
    *,
    decided: bool,
    entity_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[ApprovalRow]:
    """Runs waiting for approval (oldest first) or already decided (newest first), across
    agents. A Finance Admin sees everyone's; a user only the runs they submitted."""
    query = _in_entity(_visible_runs(user), entity_id)
    if decided:
        query = query.where(AgentRun.status.in_(DECIDED_STATUSES)).order_by(
            AgentRun.updated_at.desc()
        )
    else:
        query = query.where(AgentRun.status == RunStatus.PENDING_APPROVAL).order_by(
            AgentRun.submitted_at
        )
    runs = list(await session.scalars(query.limit(limit)))
    agents = {
        a.id: a
        for a in await session.scalars(
            select(Agent).where(Agent.id.in_({r.agent_id for r in runs}))
        )
    }
    people = await _people(session, {r.preparer_id for r in runs})
    refs = await _business_refs(session, runs)
    ents = await _entities(session, runs)
    return [
        ApprovalRow(
            RunSummary(
                **_summary(r, agents[r.agent_id], people[r.preparer_id], refs.get(r.id), ents)
            ),
            r.submitted_at,
            r.decided_at,
        )
        for r in runs
    ]


# --- worklist ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunWork:
    """One run that needs (or waits for) someone, for the My Worklist page."""

    kind: str  # changes_requested | validation_failed | ready_to_submit | draft | approve | waiting
    summary: RunSummary
    since: datetime  # what the age is measured from
    note: str | None  # e.g. the reviewer's comment, or why it's waiting
    submitted_at: datetime | None


async def work_runs(session: AsyncSession, user: User) -> list[RunWork]:
    """The viewer's own open runs, plus (Finance Admin) runs they can approve right now."""
    own_open = (
        RunStatus.CHANGES_REQUESTED,
        RunStatus.VALIDATION_FAILED,
        RunStatus.ANALYZED,
        RunStatus.DRAFT,
        RunStatus.PENDING_APPROVAL,
    )
    visible = _visible_runs(user)
    runs = list(
        await session.scalars(
            visible.where(
                (AgentRun.preparer_id == user.id) & AgentRun.status.in_(own_open)
                | (AgentRun.status == RunStatus.PENDING_APPROVAL)
            ).order_by(AgentRun.updated_at)
        )
    )
    if not runs:
        return []
    reviews: dict[uuid.UUID, list[RunReview]] = {}
    for review in await session.scalars(
        select(RunReview)
        .where(RunReview.run_id.in_([r.id for r in runs]))
        .order_by(RunReview.created_at)
    ):
        reviews.setdefault(review.run_id, []).append(review)
    agents = {
        a.id: a
        for a in await session.scalars(
            select(Agent).where(Agent.id.in_({r.agent_id for r in runs}))
        )
    }
    people = await _people(session, {r.preparer_id for r in runs})
    refs = await _business_refs(session, runs)
    ents = await _entities(session, runs)

    items = []
    for run in runs:
        summary = RunSummary(
            **_summary(run, agents[run.agent_id], people[run.preparer_id], refs.get(run.id), ents)
        )
        own = run.preparer_id == user.id
        run_reviews = reviews.get(run.id, [])
        kind: str | None = None
        note: str | None = None
        since = run.updated_at
        if run.status == RunStatus.PENDING_APPROVAL:
            blocked = await _review_blocked(session, user, run, run_reviews)
            since = run.submitted_at or run.updated_at
            if blocked is None:
                kind = "approve"
                got = len(_round_approvals(run, run_reviews))
                if run.required_approvals > 1:
                    note = f"{got} of {run.required_approvals} approvals so far"
            elif own:
                kind = "waiting"
                got = len(_round_approvals(run, run_reviews))
                note = f"{got} of {run.required_approvals} approvals"
        elif own and run.status == RunStatus.CHANGES_REQUESTED:
            kind = "changes_requested"
            last = next(
                (
                    r
                    for r in reversed(run_reviews)
                    if r.decision == ReviewDecision.CHANGES_REQUESTED
                ),
                None,
            )
            note = last.comment if last else None
        elif own and run.status == RunStatus.VALIDATION_FAILED:
            kind = "validation_failed"
            note = f"{len(run.validation_errors or [])} field(s) to fix"
        elif own and run.status == RunStatus.ANALYZED:
            kind = "ready_to_submit"
            note = run.headline
        elif own and run.status == RunStatus.DRAFT:
            kind = "draft"
        if kind is not None:
            items.append(RunWork(kind, summary, since, note, run.submitted_at))
    return items


# --- overview ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorklistRow:
    run_id: uuid.UUID
    agent_key: str
    agent_name: str
    reference: str
    entity_code: str | None
    owner: str  # the preparer
    exceptions: int  # high and warning findings
    status: RunStatus
    status_label: str
    priority: RunPriority
    created_at: datetime


@dataclass(frozen=True)
class RunStats:
    runs_this_period: int
    pending_review: int
    high_priority: int
    worklist: list[WorklistRow]


OPEN_STATUSES = (
    RunStatus.VALIDATION_FAILED,
    RunStatus.ANALYZED,
    RunStatus.PENDING_APPROVAL,
    RunStatus.CHANGES_REQUESTED,
)


def _visible_runs(user: User) -> Select[AgentRun]:
    return _own_runs(select(AgentRun).where(AgentRun.agent_id.in_(visible_agent_ids(user))), user)


async def run_stats(
    session: AsyncSession,
    user: User,
    start: datetime,
    end: datetime,
    entity_id: uuid.UUID | None = None,
    agent_key: str | None = None,
    priority: RunPriority | None = None,
    limit: int = 8,
) -> RunStats:
    """Numbers for the overview, limited to runs the user can see, optionally narrowed to one
    entity, agent and/or priority."""

    async def count(query: Select[AgentRun]) -> int:
        return await session.scalar(select(func.count()).select_from(query.subquery())) or 0

    base = _in_entity(_visible_runs(user), entity_id)
    if agent_key is not None:
        base = base.where(AgentRun.agent_id.in_(select(Agent.id).where(Agent.key == agent_key)))
    if priority is not None:
        base = base.where(AgentRun.priority == priority)
    runs_this_period = await count(
        base.where(
            AgentRun.created_at >= start,
            AgentRun.created_at < end,
            AgentRun.status != RunStatus.DRAFT,
        )
    )
    pending = await count(base.where(AgentRun.status == RunStatus.PENDING_APPROVAL))
    high = await count(
        base.where(AgentRun.priority == RunPriority.HIGH, AgentRun.status.in_(OPEN_STATUSES))
    )

    open_runs = list(
        await session.scalars(
            base.where(AgentRun.status.in_(OPEN_STATUSES))
            .order_by(
                case((AgentRun.priority == RunPriority.HIGH, 0), else_=1),
                AgentRun.updated_at.desc(),
            )
            .limit(limit)
        )
    )
    agents = {
        a.id: a
        for a in await session.scalars(
            select(Agent).where(Agent.id.in_({r.agent_id for r in open_runs}))
        )
    }
    refs = await _business_refs(session, open_runs)
    ents = await _entities(session, open_runs)
    owners = await _people(session, {r.preparer_id for r in open_runs})
    exceptions = dict(
        (
            await session.execute(
                select(RunFlag.run_id, func.count())
                .where(
                    RunFlag.run_id.in_([r.id for r in open_runs]),
                    RunFlag.severity.in_([FlagSeverity.HIGH, FlagSeverity.WARNING]),
                )
                .group_by(RunFlag.run_id)
            )
        ).all()
    )
    worklist = [
        WorklistRow(
            run_id=r.id,
            agent_key=agents[r.agent_id].key,
            agent_name=agents[r.agent_id].short_name,
            reference=refs.get(r.id, r.reference),
            entity_code=ents[r.entity_id].code if r.entity_id in ents else None,
            owner=owners[r.preparer_id].full_name,
            exceptions=exceptions.get(r.id, 0),
            status=r.status,
            status_label=STATUS_LABELS[r.status],
            priority=r.priority,
            created_at=r.created_at,
        )
        for r in open_runs
    ]
    return RunStats(runs_this_period, pending, high, worklist)


async def search_runs(session: AsyncSession, user: User, term: str, limit: int) -> list[RunSummary]:
    """Runs the user may see whose reference (RUN-01006 or 1006), headline or business
    reference (e.g. the bill number) contains the term, newest first."""
    pattern = f"%{term}%"
    matches: list[ColumnElement[bool]] = [
        AgentRun.reference_sql().ilike(pattern),
        AgentRun.headline.ilike(pattern),
    ]
    if term.isdigit():
        matches.append(AgentRun.run_number == int(term))
    for agent in await session.scalars(select(Agent).where(Agent.id.in_(visible_agent_ids(user)))):
        definition = get_agent_definition(agent.key)
        if definition and definition.run_model and definition.reference_field:
            model = definition.run_model
            column = getattr(model, definition.reference_field)
            matches.append(AgentRun.id.in_(select(model.run_id).where(column.ilike(pattern))))
    runs = list(
        await session.scalars(
            _visible_runs(user)
            .where(or_(*matches))
            .order_by(AgentRun.run_number.desc())
            .limit(limit)
        )
    )
    agents = {
        a.id: a
        for a in await session.scalars(
            select(Agent).where(Agent.id.in_({r.agent_id for r in runs}))
        )
    }
    people = await _people(session, {r.preparer_id for r in runs})
    refs = await _business_refs(session, runs)
    ents = await _entities(session, runs)
    return [
        RunSummary(**_summary(r, agents[r.agent_id], people[r.preparer_id], refs.get(r.id), ents))
        for r in runs
    ]
