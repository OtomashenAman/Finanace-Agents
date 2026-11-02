"""Manual posting tasks: proposed -> recorded_unverified -> verified.

An approved case proposes the posting; the Finance Admin posts it in QuickBooks outside the
application and records the transaction ID.
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
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.common.people import DELETED, name_of, names
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.exceptions import StaleVersionError
from src.app.service_pod.core.cases.models import LOCKED_STATUSES, CaseStatus, PodCase
from src.app.service_pod.core.hooks import hooks_for
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.tasks import erp_posting
from src.app.service_pod.core.tasks.erp_posting import ERP_KINDS
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskStatus
from src.app.service_pod.core.tasks.schemas import TaskAction, TaskCreate, TaskOut
from src.app.service_pod.core.workflows import PodKey, keys_in

ACTIONS = ("record", "post", "verify", "cancel")


class TaskNotFoundError(AppError):
    status_code = 404
    code = "posting_task_not_found"
    message = "Posting task not found."


class TaskRefusedError(AppError):
    status_code = 409
    code = "posting_task_refused"


def _guard(task: PodPostingTask, action: str) -> str | None:
    """None when `action` can be done on the task now, else why not."""
    match action:
        case "record":
            if task.status != TaskStatus.PROPOSED:
                return "Only a proposed posting can be recorded."
            if task.kind in ERP_KINDS:
                return "The app posts this to the ERP: use post."
        case "post":
            if task.kind not in ERP_KINDS:
                return "Post this one in QuickBooks yourself, then record it."
            if task.status != TaskStatus.PROPOSED:
                return "Only a proposed posting can be posted."
        case "verify":
            if task.status != TaskStatus.RECORDED_UNVERIFIED:
                return "Verify after the posting is recorded."
        case "cancel":
            if task.status != TaskStatus.PROPOSED:
                return (
                    "A recorded posting can't be cancelled; verify it or correct it in QuickBooks."
                )
    return None


async def _outs(session: AsyncSession, tasks: list[PodPostingTask]) -> list[TaskOut]:
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
            external_txn_id=t.external_txn_id,
            recorded_by=name_of(people, t.recorded_by),
            recorded_at=t.recorded_at,
            verified_by=name_of(people, t.verified_by),
            verified_at=t.verified_at,
            verification_snapshot_id=t.verification_snapshot_id,
            verification=t.verification,
            created_at=t.created_at,
            allowed_actions={a: _guard(t, a) for a in ACTIONS},
        )
        for t in tasks
    ]


async def tasks_for_case(session: AsyncSession, case: PodCase) -> list[TaskOut]:
    rows = await session.scalars(
        select(PodPostingTask)
        .where(PodPostingTask.case_id == case.id)
        .order_by(PodPostingTask.created_at)
    )
    return await _outs(session, list(rows))


async def list_tasks(session: AsyncSession, status: TaskStatus | None) -> list[TaskOut]:
    """The manual QuickBooks queue, newest first."""
    query = (
        select(PodPostingTask)
        .join(PodCase, PodCase.id == PodPostingTask.case_id)
        .where(PodCase.workflow.in_(keys_in(PodKey.SERVICE)))  # the Service POD's queue
        .order_by(PodPostingTask.updated_at.desc())
        .limit(300)
    )
    if status is not None:
        query = query.where(PodPostingTask.status == status)
    return await _outs(session, list(await session.scalars(query)))


async def propose_task(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    body: TaskCreate,
    ctx: RequestContext,
) -> TaskOut:
    case = await load_case(session, case_id, lock=True, access=access)
    task = await add_task(session, case, body, access.user.id)
    _event(session, ctx, access, case, task, f"proposed manual posting for {task.reference}")
    await session.commit()
    return (await _outs(session, [task]))[0]


async def add_task(
    session: AsyncSession, case: PodCase, body: TaskCreate, proposed_by: uuid.UUID
) -> PodPostingTask:
    """Queue a posting for the Finance Admin (caller records and commits)."""
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
        proposed_by=proposed_by,
    )
    session.add(task)
    await session.flush()
    return task


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
    same = ("company_id", "entity_id", "currency", "basis")
    differing = [f for f in same if getattr(fresh, f) != getattr(original, f)]
    # A bank statement extends a snapshot: compare where each one's books came from
    if await snapshots.origin_type(session, fresh) != await snapshots.origin_type(
        session, original
    ):
        differing.append("source type")
    if differing:
        problems.append(f"The fresh snapshot differs in {', '.join(differing)}.")
    if task.recorded_at is None or fresh.created_at <= task.recorded_at:
        problems.append("The snapshot was imported before the posting was recorded.")
    doc = snapshots.document(fresh)
    txn = task.external_txn_id
    found = (
        erp_posting.present(task, doc)
        or any(p.id == txn or p.reference == txn for p in doc.payments or [])
        or any(
            # a journal's lines are "<txn>:<n>" (one row per account); QuickBooks users
            # usually know a transaction by its number
            (t.id == txn or t.id.startswith(f"{txn}:") or t.document_ref == txn)
            and t.status == "Posted"
            for t in doc.transactions or []
        )
    )
    if not found:
        problems.append(f"Transaction {txn} isn't in the fresh snapshot.")
    verify = hooks_for(case.workflow).verify_posting
    if verify is not None and found:
        problems.extend(verify(task, case, snapshots.document(original), doc))
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
    case = await load_case(session, task.case_id, access=access)
    if task.version != body.expected_version:
        raise StaleVersionError("This task was changed by someone else. Refresh and retry.")
    if case.status in LOCKED_STATUSES - {CaseStatus.COMPLETED}:
        raise TaskRefusedError(f"{case.reference} is {case.status.value}.")
    reason = _guard(task, body.action)
    if reason is not None:
        raise TaskRefusedError(reason)

    now = utcnow()
    if body.action == "record":
        if not body.external_txn_id:
            raise TaskRefusedError("Enter the QuickBooks transaction ID of the posting.")
        task.status = TaskStatus.RECORDED_UNVERIFIED
        task.external_txn_id = body.external_txn_id.strip()
        task.recorded_by, task.recorded_at = access.user.id, now
        summary = f"recorded QuickBooks transaction {task.external_txn_id} (not yet verified)"
    elif body.action == "post":
        try:
            name = await erp_posting.post(session, task, case)
        except erp_posting.PostingError as exc:
            raise TaskRefusedError(str(exc)) from exc
        task.status = TaskStatus.RECORDED_UNVERIFIED
        task.external_txn_id = name
        task.recorded_by, task.recorded_at = access.user.id, now
        summary = f"posted {task.reference} to the ERP as {name} (not yet verified)"
    elif body.action == "verify":
        if body.snapshot_id is None:
            raise TaskRefusedError("Choose the fresh snapshot that shows the posting.")
        fresh = await snapshots.load_snapshot(session, body.snapshot_id)
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
            "posted_by_app": task.kind in ERP_KINDS,
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
    return (await _outs(session, [task]))[0]
