import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import AnalysisContext, BaseAgent
from src.app.agent_catalog.agents.fields import draft_schema, form_fields
from src.app.agent_catalog.exceptions import AgentNotFoundError
from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.registry import get_agent_definition
from src.app.agent_catalog.runs import narrative as narrative_service
from src.app.agent_catalog.runs.exceptions import (
    DocumentConflictError,
    DocumentNotFoundError,
    DocumentRejectedError,
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
    AgentRun,
    AgentRunDetail,
    RunDocument,
    RunFlag,
    RunNarrative,
    RunPriority,
    RunReview,
    RunSourceSnapshot,
    RunStatus,
)
from src.app.agent_catalog.runs.schemas import (
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
    RunDetail,
    RunPermissions,
    RunSourceOut,
    RunSummary,
    SourceLink,
)
from src.app.agent_catalog.service import ADMIN_CAPACITIES, visible_agent_ids
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


async def _load(
    session: AsyncSession, access: AgentAccess, run_id: uuid.UUID, *, lock: bool = False
) -> tuple[AgentRun, AgentRunDetail]:
    query = select(AgentRun).where(AgentRun.id == run_id, AgentRun.agent_id == access.agent.id)
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
    run: AgentRun, agent: Agent, preparer: Person, business_ref: str | None
) -> dict[str, Any]:
    return {
        "id": run.id,
        "reference": run.reference,
        "agent_key": agent.key,
        "agent_name": agent.short_name,
        "business_reference": business_ref,
        "status": run.status,
        "status_label": STATUS_LABELS[run.status],
        "priority": run.priority,
        "headline": run.headline,
        "preparer": preparer,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


async def list_runs(session: AsyncSession, user: User, key: str) -> list[RunSummary]:
    access = await _access(session, user, key)
    runs = list(
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.agent_id == access.agent.id)
            .order_by(AgentRun.run_number.desc())
            .limit(50)
        )
    )
    people = await _people(session, {r.preparer_id for r in runs})
    refs = await _business_refs(session, runs)
    return [
        RunSummary(**_summary(r, access.agent, people[r.preparer_id], refs.get(r.id))) for r in runs
    ]


async def get_run(session: AsyncSession, user: User, key: str, run_id: uuid.UUID) -> RunDetail:
    access = await _access(session, user, key)
    run, detail = await _load(session, access, run_id)
    return await _detail(session, access, run, detail)


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
    people = await _people(session, {run.preparer_id} | {r.reviewer_id for r in reviews})
    refs = await _business_refs(session, [run])
    snapshot = await session.get(RunSourceSnapshot, run.id)

    user = access.user
    is_owner = run.preparer_id == user.id
    permissions = RunPermissions(
        can_edit=is_owner and is_allowed(run.status, RunAction.EDIT),
        can_analyze=is_owner and is_allowed(run.status, RunAction.ANALYZE),
        can_submit=is_owner and is_allowed(run.status, RunAction.SUBMIT),
        can_review=(
            AgentCapacity.REVIEWER in access.capacities
            and (access.is_admin or not is_owner)
            and is_allowed(run.status, RunAction.REVIEW)
        ),
        can_delete=is_owner and is_allowed(run.status, RunAction.DELETE),
    )
    return RunDetail(
        **_summary(run, access.agent, people[run.preparer_id], refs.get(run.id)),
        input={k: _jsonable(v) for k, v in _input_values(access, detail).items()},
        validation_errors=(
            [FieldError(**e) for e in run.validation_errors] if run.validation_errors else None
        ),
        proposed_decision=run.proposed_decision,
        policy_version=run.policy_version,
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


async def create_run(session: AsyncSession, user: User, key: str, ctx: RequestContext) -> RunDetail:
    access = await _access(session, user, key)
    if not access.definition.has_workspace():
        raise WorkspaceUnavailableError
    if not access.agent.is_active:
        raise WorkspaceUnavailableError("This agent is disabled.")
    if AgentCapacity.PREPARER not in access.capacities:
        raise RunPermissionError("Only users assigned as preparer for this agent can start a run.")

    run = AgentRun(
        agent_id=access.agent.id,
        preparer_id=user.id,
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
    record_event(session, "run.created", ctx, actor_id=user.id, run=run.reference, agent=key)
    await session.commit()
    return await _detail(session, access, run, detail)


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
    analysis = await access.definition.analyze(
        data,
        AnalysisContext(session=session, run=run, document_count=len(documents), data=finance_data),
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
    run.policy_version = access.definition.policy_version
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

    # The LLM call happens after the commit so a slow provider never holds the row lock
    await narrative_service.generate(
        session, run, access.definition, data, analysis, documents, llm
    )
    await session.commit()
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

    run.result_hash = _result_hash(run, await _detail(session, access, run, detail))
    run.status = RunStatus.PENDING_APPROVAL
    run.submitted_at = utcnow()
    record_event(
        session,
        "run.submitted",
        ctx,
        actor_id=user.id,
        run=run.reference,
        result_hash=run.result_hash,
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
    if AgentCapacity.REVIEWER not in access.capacities:
        raise RunPermissionError("You are not assigned as a reviewer for this agent.")
    # Segregation of duties for users; a Finance Admin may approve their own run (audited)
    self_review = run.preparer_id == user.id
    if self_review and not access.is_admin:
        raise RunPermissionError("You can't review a run you prepared (segregation of duties).")
    ensure_allowed(run.status, RunAction.REVIEW)
    assert run.result_hash is not None  # noqa: S101 - set on submit

    session.add(
        RunReview(
            run_id=run.id,
            reviewer_id=user.id,
            decision=body.decision,
            comment=body.comment.strip(),
            result_hash=run.result_hash,
        )
    )
    run.status = REVIEW_OUTCOME[body.decision]
    run.decided_at = utcnow() if run.status != RunStatus.CHANGES_REQUESTED else None
    record_event(
        session,
        f"run.{body.decision.value}",
        ctx,
        actor_id=user.id,
        run=run.reference,
        result_hash=run.result_hash,
        self_review=self_review,
    )
    await session.commit()
    return await _detail(session, access, run, detail)


# --- overview ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorklistRow:
    run_id: uuid.UUID
    agent_key: str
    agent_name: str
    reference: str
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
    return select(AgentRun).where(AgentRun.agent_id.in_(visible_agent_ids(user)))


async def run_stats(
    session: AsyncSession, user: User, start: datetime, end: datetime, limit: int = 8
) -> RunStats:
    """Numbers for the overview, limited to agents the user can see."""

    async def count(query: Select[AgentRun]) -> int:
        return await session.scalar(select(func.count()).select_from(query.subquery())) or 0

    base = _visible_runs(user)
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
    worklist = [
        WorklistRow(
            run_id=r.id,
            agent_key=agents[r.agent_id].key,
            agent_name=agents[r.agent_id].short_name,
            reference=refs.get(r.id, r.reference),
            status=r.status,
            status_label=STATUS_LABELS[r.status],
            priority=r.priority,
            created_at=r.created_at,
        )
        for r in open_runs
    ]
    return RunStats(runs_this_period, pending, high, worklist)
