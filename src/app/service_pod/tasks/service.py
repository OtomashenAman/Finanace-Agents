"""Manual posting tasks: proposed -> approved -> recorded_unverified -> verified.

The preparer proposes from an approved case; a Finance Admin (poster) who didn't propose it
approves, posts it in QuickBooks outside the application and records the transaction ID.
Verification needs a fresh snapshot of the same company/entity/currency/basis/source type,
imported after the posting was recorded, that actually contains the transaction.
"""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.service_pod.access.service import PodAccess
from src.app.service_pod.canonical import plain
from src.app.service_pod.cases.access import CaseRole, load_case, roles_on
from src.app.service_pod.cases.exceptions import StaleVersionError
from src.app.service_pod.cases.models import LOCKED_STATUSES, CaseStatus, PodCase
from src.app.service_pod.people import DELETED, name_of, names
from src.app.service_pod.snapshots import service as snapshots
from src.app.service_pod.snapshots.models import PodSnapshot
from src.app.service_pod.tasks.models import PodPostingTask, TaskStatus
from src.app.service_pod.tasks.schemas import TaskAction, TaskCreate, TaskOut

ACTIONS = ("approve", "record", "verify", "cancel")


class TaskNotFoundError(AppError):
    status_code = 404
    code = "posting_task_not_found"
    message = "Posting task not found."


class TaskRefusedError(AppError):
    status_code = 409
    code = "posting_task_refused"


def _guard(task: PodPostingTask, access: PodAccess, action: str) -> str | None:
    """None when the viewer may do `action` on the task now, else why not."""
    if not access.is_poster:
        return "Only a Finance Admin with posting rights handles posting tasks."
    match action:
        case "approve":
            if task.status != TaskStatus.PROPOSED:
                return "Only a proposed task can be approved."
            if task.proposed_by == access.user.id:
                return "Someone other than the proposer must approve it."
        case "record":
            if task.status != TaskStatus.APPROVED:
                return "Record the posting once the task is approved."
            if task.proposed_by == access.user.id:
                return "The proposer can't record the posting."
        case "verify":
            if task.status != TaskStatus.RECORDED_UNVERIFIED:
                return "Verify after the posting is recorded."
        case "cancel":
            if task.status not in (TaskStatus.PROPOSED, TaskStatus.APPROVED):
                return (
                    "A recorded posting can't be cancelled; verify it or correct it in QuickBooks."
                )
    return None


async def _outs(
    session: AsyncSession, access: PodAccess, tasks: list[PodPostingTask]
) -> list[TaskOut]:
    if not tasks:
        return []
    cases = {
        c.id: c
        for c in await session.scalars(
            select(PodCase).where(PodCase.id.in_({t.case_id for t in tasks}))
        )
    }
    people = await names(
        session,
        [
            *(t.proposed_by for t in tasks),
            *(t.approved_by for t in tasks),
            *(t.recorded_by for t in tasks),
            *(t.verified_by for t in tasks),
        ],
    )
    return [
        TaskOut(
            id=t.id,
            case_id=t.case_id,
            case_reference=cases[t.case_id].reference,
            workflow=cases[t.case_id].workflow,
            kind=t.kind,
            reference=t.reference,
            status=t.status,
            version=t.version,
            instructions=t.instructions,
            note=t.note,
            proposed_by=people.get(t.proposed_by, DELETED),
            approved_by=name_of(people, t.approved_by),
            approved_at=t.approved_at,
            external_txn_id=t.external_txn_id,
            recorded_by=name_of(people, t.recorded_by),
            recorded_at=t.recorded_at,
            verified_by=name_of(people, t.verified_by),
            verified_at=t.verified_at,
            verification_snapshot_id=t.verification_snapshot_id,
            verification=t.verification,
            created_at=t.created_at,
            allowed_actions={a: _guard(t, access, a) for a in ACTIONS},
        )
        for t in tasks
    ]


async def tasks_for_case(session: AsyncSession, access: PodAccess, case: PodCase) -> list[TaskOut]:
    rows = await session.scalars(
        select(PodPostingTask)
        .where(PodPostingTask.case_id == case.id)
        .order_by(PodPostingTask.created_at)
    )
    return await _outs(session, access, list(rows))


async def list_tasks(
    session: AsyncSession, access: PodAccess, status: TaskStatus | None
) -> list[TaskOut]:
    """The Finance Admin's queue. Posters see the tasks, not the whole case behind them."""
    if not (access.is_poster or access.is_admin):
        return []
    query = (
        select(PodPostingTask)
        .join(PodCase, PodCase.id == PodPostingTask.case_id)
        .order_by(PodPostingTask.updated_at.desc())
        .limit(300)
    )
    if access.entity_ids is not None:
        query = query.where(PodCase.entity_id.in_(access.entity_ids))
    if status is not None:
        query = query.where(PodPostingTask.status == status)
    return await _outs(session, access, list(await session.scalars(query)))


async def propose_task(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    body: TaskCreate,
    ctx: RequestContext,
) -> TaskOut:
    case = await load_case(session, access, case_id, lock=True)
    if CaseRole.OWNER not in roles_on(case, access):
        raise TaskRefusedError("Only the case's preparer proposes posting tasks.")
    if case.status != CaseStatus.APPROVED:
        raise TaskRefusedError("A posting task can only come from an approved case.")
    snapshot = await session.get(PodSnapshot, case.snapshot_id)
    assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
    key = hashlib.sha256(
        "|".join(
            [snapshot.company_id, snapshot.entity_code, body.kind.value, body.reference.lower()]
        ).encode()
    ).hexdigest()
    if await session.scalar(select(PodPostingTask.id).where(PodPostingTask.task_key == key)):
        raise TaskRefusedError(
            f"A {body.kind.value.replace('_', ' ')} task for {body.reference} already exists."
        )
    task = PodPostingTask(
        case_id=case.id,
        kind=body.kind,
        task_key=key,
        reference=body.reference,
        status=TaskStatus.PROPOSED,
        instructions=plain(body.instructions),
        note=body.note,
        proposed_by=access.user.id,
    )
    session.add(task)
    await session.flush()
    _event(session, ctx, access, case, task, f"proposed manual posting for {task.reference}")
    await session.commit()
    return (await _outs(session, access, [task]))[0]


def _event(
    session: AsyncSession,
    ctx: RequestContext,
    access: PodAccess,
    case: PodCase,
    task: PodPostingTask,
    summary: str,
) -> None:
    record_event(
        session,
        f"pod.task_{task.status.value}",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        case_id=str(case.id),
        task_id=str(task.id),
        external_txn_id=task.external_txn_id,
        summary=f"{case.reference}: {summary}",
    )


async def _verification(
    session: AsyncSession, task: PodPostingTask, case: PodCase, fresh: PodSnapshot
) -> list[str]:
    """Problems that stop verification (empty list: verified)."""
    original = await session.get(PodSnapshot, case.snapshot_id)
    assert original is not None  # noqa: S101
    problems = []
    if fresh.sha256 == original.sha256:
        problems.append("The snapshot is the one the case started from, not a fresh export.")
    same = ("company_id", "entity_id", "currency", "basis", "source_type")
    differing = [f for f in same if getattr(fresh, f) != getattr(original, f)]
    if differing:
        problems.append(f"The fresh snapshot differs in {', '.join(differing)}.")
    if task.recorded_at is None or fresh.created_at <= task.recorded_at:
        problems.append("The snapshot was imported before the posting was recorded.")
    doc = snapshots.document(fresh)
    txn = task.external_txn_id
    found = any(p.id == txn or p.reference == txn for p in doc.payments or []) or any(
        t.id == txn and t.status == "Posted" for t in doc.transactions or []
    )
    if not found:
        problems.append(f"Transaction {txn} isn't in the fresh snapshot.")
    return problems


async def run_action(
    session: AsyncSession,
    access: PodAccess,
    task_id: uuid.UUID,
    body: TaskAction,
    ctx: RequestContext,
) -> TaskOut:
    task = await session.get(PodPostingTask, task_id, with_for_update=True)
    if task is None:
        raise TaskNotFoundError
    case = await session.get(PodCase, task.case_id)
    assert case is not None  # noqa: S101
    if not (access.is_poster and access.can_see_entity(case.entity_id)):
        raise TaskNotFoundError
    if task.version != body.expected_version:
        raise StaleVersionError("This task was changed by someone else. Refresh and retry.")
    if case.status in LOCKED_STATUSES - {CaseStatus.COMPLETED}:
        raise TaskRefusedError(f"{case.reference} is {case.status.value}.")
    reason = _guard(task, access, body.action)
    if reason is not None:
        raise TaskRefusedError(reason)

    now = utcnow()
    if body.action == "approve":
        task.status, task.approved_by, task.approved_at = TaskStatus.APPROVED, access.user.id, now
        summary = f"approved manual posting for {task.reference}"
    elif body.action == "record":
        if not body.external_txn_id:
            raise TaskRefusedError("Enter the QuickBooks transaction ID of the posting.")
        task.status = TaskStatus.RECORDED_UNVERIFIED
        task.external_txn_id = body.external_txn_id.strip()
        task.recorded_by, task.recorded_at = access.user.id, now
        summary = f"recorded QuickBooks transaction {task.external_txn_id} (not yet verified)"
    elif body.action == "verify":
        if body.snapshot_id is None:
            raise TaskRefusedError("Choose the fresh snapshot that shows the posting.")
        fresh = await snapshots.get_visible(session, access, body.snapshot_id)
        problems = await _verification(session, task, case, fresh)
        if problems:
            raise TaskRefusedError(" ".join(problems))
        task.status = TaskStatus.VERIFIED
        task.verified_by, task.verified_at = access.user.id, now
        task.verification_snapshot_id = fresh.id
        task.verification = {
            "snapshot_sha256": fresh.sha256,
            "imported_at": fresh.created_at.isoformat(),
            "transaction": task.external_txn_id,
            "checks": [
                "fresh digest",
                "same company and basis",
                "imported after recording",
                "transaction present",
            ],
        }
        summary = f"verified transaction {task.external_txn_id} against a fresh snapshot"
    else:
        task.status = TaskStatus.CANCELLED
        summary = f"cancelled manual posting for {task.reference}"
    if body.note:
        task.note = body.note
    task.version += 1
    _event(session, ctx, access, case, task, summary)
    await session.commit()
    return (await _outs(session, access, [task]))[0]
