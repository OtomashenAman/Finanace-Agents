"""The case engine shared by the five workflows.

Every change goes through run_action with the version the caller last saw. Approvals bind a
fingerprint of the case's content (source, selection, results, review tasks, actions,
commitments): changing any of it after a review sends the case back to review, so nobody
can approve one thing and have another go out. Reviewers act only on cases they didn't
prepare, and the final approver must be yet another person.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.entities import service as entities
from src.app.service_pod.access.service import PodAccess
from src.app.service_pod.canonical import canonical, fingerprint, plain
from src.app.service_pod.cases.access import (
    CaseRole,
    load_case,
    roles_on,
    visible_cases_clause,
)
from src.app.service_pod.cases.exceptions import (
    CaseActionError,
    InvalidActionPayloadError,
    SourceCoverageError,
)
from src.app.service_pod.cases.models import (
    LOCKED_STATUSES,
    CaseStatus,
    CommitmentStatus,
    Decision,
    Gate,
    PodApproval,
    PodCase,
    PodCommitment,
    PodOwnedAction,
    PodReviewTask,
    ReviewTaskStatus,
)
from src.app.service_pod.cases.schemas import (
    AddActionPayload,
    AddReviewTaskPayload,
    ApprovalOut,
    CancelPayload,
    CaseAction,
    CaseCreate,
    CaseDetail,
    CaseSummary,
    CommitmentOut,
    DecideCommitmentPayload,
    DecisionPayload,
    EditPayload,
    EmptyPayload,
    OwnedActionOut,
    PersonRef,
    ProposeCommitmentPayload,
    ResolveReviewTaskPayload,
    ReviewQueueItem,
    ReviewTaskOut,
    UpdateActionPayload,
)
from src.app.service_pod.messaging import service as messaging
from src.app.service_pod.messaging.models import Direction, MessageStatus, PodMessage
from src.app.service_pod.people import DELETED, name_of, names
from src.app.service_pod.snapshots import service as snapshots
from src.app.service_pod.snapshots.contract import Collection
from src.app.service_pod.snapshots.models import PodSnapshot
from src.app.service_pod.tasks import service as tasks
from src.app.service_pod.tasks.models import PodPostingTask, TaskStatus
from src.app.service_pod.workflows import WORKFLOWS, Capacity

MAX_CASE_DATA = 256 * 1024  # selection / state JSON
OPEN_FOR_EDIT = frozenset({CaseStatus.DRAFT, CaseStatus.CHANGES_REQUESTED})
REVIEWED = frozenset({CaseStatus.AWAITING_FINAL, CaseStatus.APPROVED})


@dataclass
class _Children:
    approvals: list[PodApproval]
    review_tasks: list[PodReviewTask]
    actions: list[PodOwnedAction]
    commitments: list[PodCommitment]


async def _children(session: AsyncSession, case: PodCase) -> _Children:
    return _Children(
        approvals=list(
            await session.scalars(
                select(PodApproval)
                .where(PodApproval.case_id == case.id)
                .order_by(PodApproval.created_at)
            )
        ),
        review_tasks=list(
            await session.scalars(
                select(PodReviewTask)
                .where(PodReviewTask.case_id == case.id)
                .order_by(PodReviewTask.created_at)
            )
        ),
        actions=list(
            await session.scalars(
                select(PodOwnedAction)
                .where(PodOwnedAction.case_id == case.id)
                .order_by(PodOwnedAction.created_at)
            )
        ),
        commitments=list(
            await session.scalars(
                select(PodCommitment)
                .where(PodCommitment.case_id == case.id)
                .order_by(PodCommitment.created_at)
            )
        ),
    )


def case_fingerprint(case: PodCase, children: _Children) -> str:
    """What an approval vouches for. Timestamps and who-did-it are left out on purpose:
    they don't change what is being approved."""
    return fingerprint(
        {
            "snapshot": case.snapshot_sha,
            "title": case.title,
            "selection": case.selection,
            "state": case.state,
            "review_tasks": [
                [str(t.id), t.kind, t.subject, t.detail, t.blocking, t.status, t.resolution]
                for t in children.review_tasks
            ],
            "actions": [
                [str(a.id), a.title, str(a.owner_id), a.due_date, a.status, a.outcome]
                for a in children.actions
            ],
            "commitments": [
                [
                    str(c.id),
                    c.invoice_id,
                    c.amount,
                    c.expected_date,
                    c.probability,
                    c.probability_rationale,
                    c.status,
                ]
                for c in children.commitments
            ],
        }
    )


def _blockers(children: _Children) -> list[str]:
    open_tasks = [
        t for t in children.review_tasks if t.blocking and t.status == ReviewTaskStatus.OPEN
    ]
    if open_tasks:
        n = len(open_tasks)
        return [f"{n} open review task{'s' if n > 1 else ''} must be resolved first."]
    return []


async def _completion_blockers(session: AsyncSession, case: PodCase) -> list[str]:
    problems = []
    unverified = await session.scalar(
        select(func.count())
        .select_from(PodPostingTask)
        .where(
            PodPostingTask.case_id == case.id,
            PodPostingTask.status.not_in([TaskStatus.VERIFIED, TaskStatus.CANCELLED]),
        )
    )
    if unverified:
        problems.append(
            f"{unverified} manual posting task(s) aren't verified against a fresh snapshot yet."
        )
    in_flight = await session.scalar(
        select(func.count())
        .select_from(PodMessage)
        .where(
            PodMessage.case_id == case.id,
            PodMessage.status.in_([MessageStatus.SENDING, MessageStatus.SEND_UNKNOWN]),
        )
    )
    if in_flight:
        problems.append("A message is still sending or its outcome must be reconciled.")
    return problems


def _valid_review(children: _Children, current: str) -> PodApproval | None:
    reviews = [
        a
        for a in children.approvals
        if a.gate == Gate.REVIEW and a.decision == Decision.APPROVED and a.content_hash == current
    ]
    return reviews[-1] if reviews else None


# --- guards: None = allowed, else the reason --------------------------------------------


@dataclass
class _Ctx:
    session: AsyncSession
    access: PodAccess
    case: PodCase
    roles: set[CaseRole]
    children: _Children
    fingerprint: str
    blockers: list[str]
    completion_blockers: list[str]
    request: RequestContext | None = None

    @property
    def user(self) -> User:
        return self.access.user

    @property
    def locked(self) -> bool:
        return self.case.status in LOCKED_STATUSES


def _need(c: _Ctx, *roles: CaseRole) -> str | None:
    if c.locked:
        return f"The case is {c.case.status.value.replace('_', ' ')}; it can't change any more."
    if not c.roles & set(roles):
        spec = WORKFLOWS[c.case.workflow]
        if CaseRole.OWNER in roles and len(roles) == 1:
            return "Only the preparer who opened this case can do this."
        wanted = [spec.labels.get(Capacity(r.value), r.value) for r in roles if r != CaseRole.OWNER]
        who = " or ".join(wanted) if wanted else "an assigned person"
        return f"Only the {who} can do this (and not on a case they prepared)."
    return None


def _status(c: _Ctx, allowed: frozenset[CaseStatus], doing: str) -> str | None:
    if c.case.status not in allowed:
        return f"Can't {doing} while the case is {c.case.status.value.replace('_', ' ')}."
    return None


def _guard_edit(c: _Ctx) -> str | None:
    return _need(c, CaseRole.OWNER) or _status(c, OPEN_FOR_EDIT, "edit")


def _guard_submit(c: _Ctx) -> str | None:
    return (
        _need(c, CaseRole.OWNER)
        or _status(c, OPEN_FOR_EDIT, "submit")
        or (c.blockers[0] if c.blockers else None)
    )


def _guard_review(c: _Ctx) -> str | None:
    return (
        _need(c, CaseRole.REVIEWER)
        or _status(c, frozenset({CaseStatus.IN_REVIEW}), "review")
        or (c.blockers[0] if c.blockers else None)
    )


def _guard_final(c: _Ctx) -> str | None:
    if not WORKFLOWS[c.case.workflow].final_gate:
        return "This workflow has no final approval."
    problem = _need(c, CaseRole.FINAL_APPROVER) or _status(
        c, frozenset({CaseStatus.AWAITING_FINAL}), "give the final approval"
    )
    if problem:
        return problem
    review = _valid_review(c.children, c.fingerprint)
    if review is None:
        return "The review approval no longer matches the case; it must be reviewed again."
    if review.user_id == c.user.id:
        return "The final approval must come from a different person than the reviewer."
    return c.blockers[0] if c.blockers else None


def _guard_complete(c: _Ctx) -> str | None:
    return (
        _need(c, CaseRole.OWNER, CaseRole.REVIEWER)
        or _status(c, frozenset({CaseStatus.APPROVED}), "complete")
        or (c.completion_blockers[0] if c.completion_blockers else None)
    )


def _guard_cancel(c: _Ctx) -> str | None:
    return _need(c, CaseRole.OWNER) or _status(c, OPEN_FOR_EDIT, "cancel")


def _guard_work(c: _Ctx) -> str | None:
    return _need(c, CaseRole.OWNER, CaseRole.REVIEWER, CaseRole.FINAL_APPROVER)


def _guard_propose(c: _Ctx) -> str | None:
    return _need(c, CaseRole.OWNER)


def _guard_decide_commitment(c: _Ctx) -> str | None:
    return _need(c, CaseRole.REVIEWER)


# --- handlers: change the case, return (summary, content changed) -----------------------

Handler = Callable[[_Ctx, BaseModel], Awaitable[tuple[str, bool]]]


def _bounded(value: dict[str, object], what: str) -> dict[str, object]:
    data: dict[str, object] = plain(value)
    if len(canonical(data)) > MAX_CASE_DATA:
        raise InvalidActionPayloadError(f"The {what} is too large.")
    return data


async def _edit(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, EditPayload)  # noqa: S101 - dispatch guarantees the type
    if p.title is not None:
        c.case.title = p.title
    if p.selection is not None:
        c.case.selection = _bounded(p.selection, "selection")
    if p.state is not None:
        c.case.state = _bounded(p.state, "case data")
    return "Edited", True


async def _submit(c: _Ctx, _: BaseModel) -> tuple[str, bool]:
    c.case.status = CaseStatus.IN_REVIEW
    return "Submitted for review", False


async def _decide(c: _Ctx, p: BaseModel, gate: Gate) -> tuple[str, bool]:
    assert isinstance(p, DecisionPayload)  # noqa: S101
    c.session.add(
        PodApproval(
            case_id=c.case.id,
            gate=gate,
            decision=p.decision,
            user_id=c.user.id,
            content_hash=c.fingerprint,
            comment=p.comment.strip() if p.comment else None,
        )
    )
    if p.decision == Decision.APPROVED:
        final = gate == Gate.REVIEW and WORKFLOWS[c.case.workflow].final_gate
        c.case.status = CaseStatus.AWAITING_FINAL if final else CaseStatus.APPROVED
    elif p.decision == Decision.CHANGES_REQUESTED:
        c.case.status = CaseStatus.CHANGES_REQUESTED
    else:
        c.case.status = CaseStatus.REJECTED
    label = "Final decision" if gate == Gate.FINAL else "Review"
    return f"{label}: {p.decision.value.replace('_', ' ')}", False


async def _review(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    return await _decide(c, p, Gate.REVIEW)


async def _final_review(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    return await _decide(c, p, Gate.FINAL)


async def _complete(c: _Ctx, _: BaseModel) -> tuple[str, bool]:
    c.case.status = CaseStatus.COMPLETED
    c.case.completed_at = utcnow()
    return "Completed", False


async def _cancel(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, CancelPayload)  # noqa: S101
    c.case.status = CaseStatus.CANCELLED
    return f"Cancelled: {p.reason}", False


async def _add_review_task(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, AddReviewTaskPayload)  # noqa: S101
    c.session.add(
        PodReviewTask(
            case_id=c.case.id,
            kind=p.kind,
            subject=p.subject,
            detail=p.detail,
            blocking=p.blocking,
            created_by=c.user.id,
        )
    )
    return f"Raised a review task ({p.kind.value.replace('_', ' ')})", True


async def _resolve_review_task(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, ResolveReviewTaskPayload)  # noqa: S101
    task = next((t for t in c.children.review_tasks if t.id == p.task_id), None)
    if task is None:
        raise InvalidActionPayloadError("Unknown review task.")
    if task.status != ReviewTaskStatus.OPEN:
        raise CaseActionError("This review task is already resolved.")
    task.status = ReviewTaskStatus.RESOLVED
    task.resolution = p.resolution.strip()
    task.resolved_by = c.user.id
    task.resolved_at = utcnow()
    return "Resolved a review task", True


async def _add_action(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, AddActionPayload)  # noqa: S101
    owner = await c.session.get(User, p.owner_id)
    if owner is None or not owner.is_active:
        raise InvalidActionPayloadError("The action owner must be an active user.")
    c.session.add(
        PodOwnedAction(
            case_id=c.case.id,
            title=p.title,
            owner_id=owner.id,
            due_date=p.due_date,
            created_by=c.user.id,
        )
    )
    return f"Added action '{p.title}' for {owner.full_name}", True


async def _update_action(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, UpdateActionPayload)  # noqa: S101
    action = next((a for a in c.children.actions if a.id == p.action_id), None)
    if action is None:
        raise InvalidActionPayloadError("Unknown action.")
    action.status = p.status
    action.outcome = p.outcome.strip() if p.outcome else action.outcome
    return f"Action '{action.title}' is {p.status.value}", True


async def _propose_commitment(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, ProposeCommitmentPayload)  # noqa: S101
    snapshot = await c.session.get(PodSnapshot, c.case.snapshot_id)
    assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
    invoices = snapshots.document(snapshot).invoices
    if invoices is None:
        raise InvalidActionPayloadError("The case's snapshot has no invoices.")
    invoice = next((i for i in invoices if i.id == p.invoice_id), None)
    if invoice is None:
        raise InvalidActionPayloadError("That invoice isn't in the case's snapshot.")
    promised = sum(
        (
            x.amount
            for x in c.children.commitments
            if x.invoice_id == invoice.id and x.status != CommitmentStatus.REJECTED
        ),
        start=p.amount,
    )
    if promised > invoice.balance:
        raise InvalidActionPayloadError(
            f"Commitments on {invoice.number} would exceed its open balance of {invoice.balance}."
        )
    if p.source_message_id is not None:
        message = await c.session.get(PodMessage, p.source_message_id)
        if (
            message is None
            or message.case_id != c.case.id
            or message.direction != Direction.INBOUND
        ):
            raise InvalidActionPayloadError("The source must be a reply imported into this case.")
    c.session.add(
        PodCommitment(
            case_id=c.case.id,
            invoice_id=invoice.id,
            invoice_number=invoice.number,
            amount=p.amount,
            expected_date=p.expected_date,
            probability=p.probability,
            probability_rationale=p.probability_rationale,
            quote=p.quote,
            source_message_id=p.source_message_id,
            created_by=c.user.id,
        )
    )
    when = p.expected_date.isoformat() if p.expected_date else "no date yet"
    return f"Proposed a commitment of {p.amount} on {invoice.number} ({when})", True


async def _decide_commitment(c: _Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, DecideCommitmentPayload)  # noqa: S101
    commitment = next((x for x in c.children.commitments if x.id == p.commitment_id), None)
    if commitment is None:
        raise InvalidActionPayloadError("Unknown commitment.")
    if commitment.status != CommitmentStatus.PROPOSED:
        raise CaseActionError("This commitment was already decided.")
    if commitment.created_by == c.user.id:
        raise CaseActionError("You can't approve a commitment you proposed.")
    if p.decision == "approved" and commitment.expected_date is None:
        raise CaseActionError(
            "A commitment without a date can't be approved: get the date from the customer."
        )
    commitment.status = CommitmentStatus(p.decision)
    commitment.decided_by = c.user.id
    commitment.decided_at = utcnow()
    return f"Commitment on {commitment.invoice_number}: {p.decision}", True


@dataclass(frozen=True)
class _Action:
    payload: type[BaseModel]
    guard: Callable[[_Ctx], str | None]
    handler: Handler


ACTIONS: dict[str, _Action] = {
    "edit": _Action(EditPayload, _guard_edit, _edit),
    "submit": _Action(EmptyPayload, _guard_submit, _submit),
    "review": _Action(DecisionPayload, _guard_review, _review),
    "final_review": _Action(DecisionPayload, _guard_final, _final_review),
    "complete": _Action(EmptyPayload, _guard_complete, _complete),
    "cancel": _Action(CancelPayload, _guard_cancel, _cancel),
    "add_review_task": _Action(AddReviewTaskPayload, _guard_work, _add_review_task),
    "resolve_review_task": _Action(ResolveReviewTaskPayload, _guard_work, _resolve_review_task),
    "add_action": _Action(AddActionPayload, _guard_work, _add_action),
    "update_action": _Action(UpdateActionPayload, _guard_work, _update_action),
    "propose_commitment": _Action(ProposeCommitmentPayload, _guard_propose, _propose_commitment),
    "decide_commitment": _Action(
        DecideCommitmentPayload, _guard_decide_commitment, _decide_commitment
    ),
}


async def _ctx(
    session: AsyncSession, access: PodAccess, case: PodCase, request: RequestContext | None = None
) -> _Ctx:
    children = await _children(session, case)
    return _Ctx(
        session=session,
        access=access,
        case=case,
        roles=roles_on(case, access),
        children=children,
        fingerprint=case_fingerprint(case, children),
        blockers=_blockers(children),
        completion_blockers=await _completion_blockers(session, case),
        request=request,
    )


# --- public API ------------------------------------------------------------------------


async def create_case(
    session: AsyncSession, access: PodAccess, body: CaseCreate, ctx: RequestContext
) -> CaseDetail:
    spec = WORKFLOWS[body.workflow]
    access.require(spec.key, Capacity.PREPARER, "open cases")
    snapshot = await snapshots.get_visible(session, access, body.snapshot_id)
    access.require_entity(snapshot.entity_id)
    missing = sorted(spec.required - {Collection(c) for c in snapshot.coverage})
    if missing:
        raise SourceCoverageError(
            f"{spec.name} needs {', '.join(m.value.replace('_', ' ') for m in missing)}, "
            "which this snapshot doesn't contain. Import a source that supplies them; "
            "missing data is never filled in."
        )
    case = PodCase(
        workflow=spec.key,
        entity_id=snapshot.entity_id,
        snapshot_id=snapshot.id,
        snapshot_sha=snapshot.sha256,
        owner_id=access.user.id,
        title=body.title,
        status=CaseStatus.DRAFT,
        stage="start",
        selection=_bounded(body.selection, "selection"),
        state={},
    )
    session.add(case)
    await session.flush()
    record_event(
        session,
        "pod.case_created",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        case_id=str(case.id),
        workflow=spec.key.value,
        snapshot_sha=snapshot.sha256,
        summary=f"Opened {case.reference} ({spec.name}): {case.title}",
    )
    await session.commit()
    return await get_case(session, access, case.id)


async def run_action(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    body: CaseAction,
    request: RequestContext,
) -> CaseDetail:
    action = ACTIONS.get(body.action)
    if action is None:
        raise InvalidActionPayloadError(f"Unknown action {body.action!r}.")
    try:
        payload = action.payload.model_validate(body.payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise InvalidActionPayloadError(str(first["msg"]).removeprefix("Value error, ")) from exc

    case = await load_case(
        session, access, case_id, lock=True, expected_version=body.expected_version
    )
    c = await _ctx(session, access, case, request)
    reason = action.guard(c)
    if reason is not None:
        raise CaseActionError(reason)

    summary, changed = await action.handler(c, payload)
    reopened = changed and case.status in REVIEWED
    if reopened:
        case.status = CaseStatus.IN_REVIEW
    case.version += 1
    record_event(
        session,
        f"pod.case_{body.action}",
        request,
        actor_id=access.user.id,
        run=case.reference,
        case_id=str(case.id),
        version=case.version,
        status=case.status.value,
        summary=f"{case.reference}: {summary}",
    )
    if reopened:
        record_event(
            session,
            "pod.case_approvals_invalidated",
            request,
            actor_id=access.user.id,
            run=case.reference,
            case_id=str(case.id),
            summary=f"{case.reference}: content changed after review, back to review",
        )
    await session.commit()
    return await get_case(session, access, case.id)


async def _summaries(session: AsyncSession, cases: list[PodCase]) -> list[CaseSummary]:
    if not cases:
        return []
    entity_refs = await entities.refs(session, {c.entity_id for c in cases})
    owners = await names(session, (c.owner_id for c in cases))
    demo_rows = await session.execute(
        select(PodSnapshot.id, PodSnapshot.is_demo).where(
            PodSnapshot.id.in_({c.snapshot_id for c in cases})
        )
    )
    demo = dict(demo_rows.all())
    count_rows = await session.execute(
        select(PodReviewTask.case_id, func.count())
        .where(
            PodReviewTask.case_id.in_([c.id for c in cases]),
            PodReviewTask.status == ReviewTaskStatus.OPEN,
        )
        .group_by(PodReviewTask.case_id)
    )
    open_counts = dict(count_rows.all())
    return [
        CaseSummary(
            id=c.id,
            reference=c.reference,
            workflow=c.workflow,
            title=c.title,
            status=c.status,
            stage=c.stage,
            version=c.version,
            entity=entity_refs[c.entity_id],
            owner=PersonRef(id=c.owner_id, name=owners.get(c.owner_id, DELETED)),
            snapshot_id=c.snapshot_id,
            is_demo=demo.get(c.snapshot_id, False),
            open_review_tasks=open_counts.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in cases
    ]


async def list_cases(
    session: AsyncSession,
    access: PodAccess,
    workflow: str | None,
    status: CaseStatus | None,
    entity_id: uuid.UUID | None,
) -> list[CaseSummary]:
    query = (
        select(PodCase)
        .where(visible_cases_clause(access))
        .order_by(PodCase.updated_at.desc())
        .limit(300)
    )
    if workflow is not None:
        query = query.where(PodCase.workflow == workflow)
    if status is not None:
        query = query.where(PodCase.status == status)
    if entity_id is not None:
        query = query.where(PodCase.entity_id == entity_id)
    return await _summaries(session, list(await session.scalars(query)))


async def get_case(session: AsyncSession, access: PodAccess, case_id: uuid.UUID) -> CaseDetail:
    case = await load_case(session, access, case_id)
    c = await _ctx(session, access, case)
    ch = c.children
    people = await names(
        session,
        [
            *(a.user_id for a in ch.approvals),
            *(t.created_by for t in ch.review_tasks),
            *(t.resolved_by for t in ch.review_tasks),
            *(a.owner_id for a in ch.actions),
            *(x.created_by for x in ch.commitments),
            *(x.decided_by for x in ch.commitments),
        ],
    )
    snapshot = await session.get(PodSnapshot, case.snapshot_id)
    assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
    summary = (await _summaries(session, [case]))[0]
    return CaseDetail(
        **summary.model_dump(),
        snapshot=await snapshots.summary(session, snapshot),
        selection=case.selection,
        state=case.state,
        completed_at=case.completed_at,
        fingerprint=c.fingerprint,
        my_roles=sorted(r.value for r in c.roles),
        approvals=[
            ApprovalOut(
                id=a.id,
                gate=a.gate,
                decision=a.decision,
                user=PersonRef(id=a.user_id, name=people.get(a.user_id, DELETED)),
                comment=a.comment,
                content_hash=a.content_hash,
                policy_version=a.policy_version,
                valid=a.content_hash == c.fingerprint,
                created_at=a.created_at,
            )
            for a in ch.approvals
        ],
        review_tasks=[_task_out(t, people) for t in ch.review_tasks],
        owned_actions=[
            OwnedActionOut(
                id=a.id,
                title=a.title,
                owner=PersonRef(id=a.owner_id, name=people.get(a.owner_id, DELETED)),
                due_date=a.due_date,
                status=a.status,
                outcome=a.outcome,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in ch.actions
        ],
        commitments=[
            CommitmentOut(
                id=x.id,
                invoice_id=x.invoice_id,
                invoice_number=x.invoice_number,
                amount=x.amount,
                expected_date=x.expected_date,
                probability=x.probability,
                probability_rationale=x.probability_rationale,
                quote=x.quote,
                source_message_id=x.source_message_id,
                status=x.status,
                created_by=name_of(people, x.created_by),
                decided_by=name_of(people, x.decided_by),
                decided_at=x.decided_at,
                created_at=x.created_at,
            )
            for x in ch.commitments
        ],
        messages=await messaging.messages_for_case(session, case),
        artifacts=await messaging.artifacts_for_case(session, case),
        posting_tasks=await tasks.tasks_for_case(session, access, case),
        blockers=c.blockers,
        completion_blockers=c.completion_blockers,
        allowed_actions={name: a.guard(c) for name, a in ACTIONS.items()},
    )


def _task_out(t: PodReviewTask, people: dict[uuid.UUID, str]) -> ReviewTaskOut:
    return ReviewTaskOut(
        id=t.id,
        kind=t.kind,
        subject=t.subject,
        detail=t.detail,
        blocking=t.blocking,
        status=t.status,
        resolution=t.resolution,
        created_by=name_of(people, t.created_by),
        resolved_by=name_of(people, t.resolved_by),
        resolved_at=t.resolved_at,
        created_at=t.created_at,
    )


async def review_queue(session: AsyncSession, access: PodAccess) -> list[ReviewQueueItem]:
    """Open review tasks on the cases the viewer works on, oldest first."""
    rows = (
        await session.execute(
            select(PodReviewTask, PodCase)
            .join(PodCase, PodCase.id == PodReviewTask.case_id)
            .where(
                visible_cases_clause(access),
                PodReviewTask.status == ReviewTaskStatus.OPEN,
                PodCase.status.not_in(LOCKED_STATUSES),
            )
            .order_by(PodReviewTask.created_at)
            .limit(300)
        )
    ).all()
    pairs = [(task, case) for task, case in rows]
    people = await names(session, (t.created_by for t, _ in pairs))
    return [
        ReviewQueueItem(
            task=_task_out(t, people),
            case_id=case.id,
            case_reference=case.reference,
            workflow=case.workflow,
            case_title=case.title,
        )
        for t, case in pairs
    ]
