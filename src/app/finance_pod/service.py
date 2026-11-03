"""Finance POD: capacities (granted by a Finance Admin), the viewer's own access, and the
dashboard (workflow tiles with the requirement's measures, and the steps waiting on me)."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.entities import service as entities
from src.app.entities.models import LegalEntity
from src.app.finance_pod.capacities import LABELS, FinanceCapacity, label
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.models import FinanceCapacityAssignment
from src.app.finance_pod.schemas import (
    AiEvent,
    AiKind,
    AssignmentCreate,
    AssignmentOut,
    AssignmentPerson,
    CapacityOut,
    FinanceAi,
    FinanceDashboard,
    FinanceKpis,
    FinanceMe,
    HeldCapacity,
    MeasureOut,
    QueueItem,
    QueueType,
    WorkflowTile,
)
from src.app.service_pod.common.people import name_of, names
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import (
    LOCKED_STATUSES,
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskStatus,
)
from src.app.service_pod.core.cases.service import case_context, visible_condition
from src.app.service_pod.core.messaging.models import MessageStatus, PodMessage
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.steps import service as steps
from src.app.service_pod.core.steps.spec import StepKind
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskStatus
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey, workflows_in

MAX_QUEUE_CASES = 200


class AssignmentNotFoundError(AppError):
    status_code = 404
    code = "assignment_not_found"
    message = "Capacity assignment not found."


class AssignmentInvalidError(AppError):
    status_code = 422
    code = "assignment_invalid"


class AssignmentExistsError(AppError):
    status_code = 409
    code = "assignment_exists"
    message = "This person already holds that capacity for that entity."


def catalog() -> list[CapacityOut]:
    return [
        CapacityOut(key=cap, label=text, description=description)
        for cap, (text, description) in LABELS.items()
    ]


async def me(session: AsyncSession, access: PodAccess) -> FinanceMe:
    entity_ids = {e for ents in access.capacities.values() if ents for e in ents}
    refs = await entities.refs(session, entity_ids)
    return FinanceMe(
        is_admin=access.is_admin,
        capacities=[
            HeldCapacity(
                capacity=FinanceCapacity(cap),
                label=label(cap),
                entities=None if ents is None else [refs[e] for e in sorted(ents) if e in refs],
            )
            for cap, ents in sorted(access.capacities.items())
        ],
        can_open=[
            spec.key
            for spec in workflows_in(PodKey.FINANCE)
            if any(access.holds(cap) for cap in spec.plan.openers)
        ],
    )


async def _assignment_outs(
    session: AsyncSession, rows: list[FinanceCapacityAssignment]
) -> list[AssignmentOut]:
    users = {
        u.id: u
        for u in await session.scalars(select(User).where(User.id.in_({r.user_id for r in rows})))
    }
    granters = await names(session, (r.granted_by for r in rows))
    refs = await entities.refs(session, {r.entity_id for r in rows if r.entity_id})
    return [
        AssignmentOut(
            id=r.id,
            user=AssignmentPerson(
                id=r.user_id, name=users[r.user_id].full_name, email=users[r.user_id].email
            ),
            capacity=r.capacity,
            label=label(r.capacity),
            entity=refs.get(r.entity_id) if r.entity_id else None,
            granted_by=name_of(granters, r.granted_by),
            created_at=r.created_at,
        )
        for r in rows
        if r.user_id in users
    ]


async def list_assignments(session: AsyncSession) -> list[AssignmentOut]:
    rows = list(
        await session.scalars(
            select(FinanceCapacityAssignment).order_by(
                FinanceCapacityAssignment.capacity, FinanceCapacityAssignment.created_at
            )
        )
    )
    return await _assignment_outs(session, rows)


async def grant(
    session: AsyncSession, admin: User, body: AssignmentCreate, ctx: RequestContext
) -> AssignmentOut:
    user = await session.get(User, body.user_id)
    if user is None or not user.is_active:
        raise AssignmentInvalidError("Pick an active user.")
    entity = None
    if body.entity_id is not None:
        entity = await session.get(LegalEntity, body.entity_id)
        if entity is None:
            raise AssignmentInvalidError("Unknown legal entity.")
    row = FinanceCapacityAssignment(
        user_id=user.id, capacity=body.capacity, entity_id=body.entity_id, granted_by=admin.id
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AssignmentExistsError from exc
    where = entity.code if entity else "all entities"
    record_event(
        session,
        "finance.capacity_granted",
        ctx,
        actor_id=admin.id,
        user_id=str(user.id),
        capacity=body.capacity.value,
        entity_id=str(body.entity_id) if body.entity_id else None,
        summary=f"Granted {label(body.capacity)} ({where}) to {user.full_name}",
    )
    await session.commit()
    return (await _assignment_outs(session, [row]))[0]


async def revoke(
    session: AsyncSession, admin: User, assignment_id: uuid.UUID, ctx: RequestContext
) -> None:
    row = await session.get(FinanceCapacityAssignment, assignment_id)
    if row is None:
        raise AssignmentNotFoundError
    user = await session.get(User, row.user_id)
    entity = await session.get(LegalEntity, row.entity_id) if row.entity_id else None
    where = entity.code if entity else "all entities"
    who = user.full_name if user else "a deleted user"
    record_event(
        session,
        "finance.capacity_revoked",
        ctx,
        actor_id=admin.id,
        user_id=str(row.user_id),
        capacity=row.capacity.value,
        entity_id=str(row.entity_id) if row.entity_id else None,
        summary=f"Revoked {label(row.capacity)} ({where}) from {who}",
    )
    await session.delete(row)
    await session.commit()


# --- dashboard --------------------------------------------------------------------------


async def dashboard(session: AsyncSession, access: PodAccess) -> FinanceDashboard:
    cases = list(
        await session.scalars(
            select(PodCase).where(visible_condition(access)).order_by(PodCase.created_at)
        )
    )
    since = utcnow() - timedelta(days=30)
    tiles = []
    for spec in workflows_in(PodKey.FINANCE):
        # Each person sees the workflows they take part in (an admin: all)
        if not access.is_admin and not (spec.plan.capacities() & set(access.capacities)):
            continue
        mine = [c for c in cases if c.workflow == spec.key]
        tiles.append(
            WorkflowTile(
                key=spec.key,
                area="AR" if spec.key.value.startswith("ar_") else "AP",
                name=spec.name,
                prefix=spec.prefix,
                description=spec.description,
                open=sum(1 for c in mine if c.status not in LOCKED_STATUSES),
                approved=sum(1 for c in mine if c.status == CaseStatus.APPROVED),
                completed_30d=sum(
                    1
                    for c in mine
                    if c.status == CaseStatus.COMPLETED
                    and c.completed_at
                    and c.completed_at >= since
                ),
                measures=[
                    MeasureOut(
                        id=m.id, label=m.label, unit=m.unit, value=await m.compute(session, mine)
                    )
                    for m in spec.plan.measures
                ],
            )
        )
    return FinanceDashboard(
        workflows=tiles,
        my_queue=await _my_queue(session, access, cases),
        kpis=await _kpis(session, access, cases),
        ai=await _ai(session, cases),
    )


AI_EVENTS: dict[str, AiKind] = {
    "pod.case_run_agent_step": "agent_step",
    "pod.task_recorded_unverified": "posted",
    "pod.task_verified": "verified",
}


async def _ai(session: AsyncSession, cases: list[PodCase]) -> FinanceAi:
    """The agents' finished steps and the app's ERPNext postings and verifications on the
    cases the viewer sees (a step the agent couldn't finish isn't counted)."""
    seen = {str(c.id): c for c in cases}
    rows = await session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.event_type.in_(AI_EVENTS),
            AuditEvent.details["case_id"].astext.in_(list(seen) or [""]),
            AuditEvent.created_at >= utcnow() - timedelta(days=7),
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(2000)
    )
    counts: dict[str, int] = dict.fromkeys(AI_EVENTS.values(), 0)
    recent: list[AiEvent] = []
    for e in rows:
        summary = str((e.details or {}).get("summary") or "")
        if e.event_type == "pod.case_run_agent_step" and "run by the agent" not in summary:
            continue
        kind = AI_EVENTS[e.event_type]
        counts[kind] += 1
        if len(recent) < 8:
            case = seen.get(str((e.details or {}).get("case_id")))
            recent.append(
                AiEvent(at=e.created_at, kind=kind, summary=summary[:300],
                        case_id=case.id if case else None,
                        reference=case.reference if case else None)
            )  # fmt: skip
    return FinanceAi(last_7_days=counts, recent=recent)


async def _kpis(session: AsyncSession, access: PodAccess, cases: list[PodCase]) -> FinanceKpis:
    live = [c for c in cases if c.status not in LOCKED_STATUSES]
    ar = sum(1 for c in live if c.workflow.value.startswith("ar_"))
    pending = 0
    if cases:
        pending = int(
            await session.scalar(
                select(func.count())
                .select_from(PodPostingTask)
                .where(
                    PodPostingTask.case_id.in_([c.id for c in cases]),
                    PodPostingTask.status.in_(
                        [TaskStatus.PROPOSED, TaskStatus.RECORDED_UNVERIFIED]
                    ),
                )
            )
            or 0
        )
    kpis = FinanceKpis(open_ap=len(live) - ar, open_ar=ar, erp_pending=pending)
    # The newest snapshot holding the Finance POD's data (an ERP's purchasing or receivables)
    newest, doc = None, None
    for snap in await session.scalars(
        select(PodSnapshot).order_by(PodSnapshot.created_at.desc()).limit(20)
    ):
        found = snapshots.document(snap)
        if found.vendors is not None or found.clients is not None:
            newest, doc = snap, found
            break
    if newest is None or doc is None:
        return kpis
    kpis.last_snapshot_at = newest.created_at
    source = await snapshots.source_of(session, newest.id)
    kpis.source_name = source.name if source else newest.company_name
    receivables = {Cap.CREDIT_CONTROLLER.value, Cap.BILLING_ANALYST.value}
    if not (access.is_admin or access.holds_any(receivables, newest.entity_id)):
        return kpis
    if doc.sales_invoices is None:
        return kpis
    today = utcnow().date()
    late = [i for i in doc.sales_invoices if i.doc_status == "Submitted" and i.outstanding > 0
            and i.due_date is not None and i.due_date < today]  # fmt: skip
    kpis.overdue_receivables = sum((i.outstanding for i in late), Decimal(0))
    kpis.overdue_clients = len({i.client_id for i in late})
    kpis.currency = doc.currency
    return kpis


async def _my_queue(
    session: AsyncSession, access: PodAccess, cases: list[PodCase]
) -> list[QueueItem]:
    """Steps the viewer can act on now: a person's step whose capacity they hold, or an
    agent step they may start. Oldest case first."""
    items = []
    open_cases = [c for c in cases if c.status not in LOCKED_STATUSES and steps.has_steps(c)]
    for case in open_cases[:MAX_QUEUE_CASES]:
        c = await case_context(session, access, case)
        for step in steps.plan_of(case).steps:
            if step.kind == StepKind.SYSTEM:
                continue
            problem = (
                steps.agent_problem(c, step)
                if step.kind == StepKind.AGENT
                else steps.person_problem(c, step)
            )
            if problem is None and step.kind == StepKind.AGENT and step.ready is not None:
                unready = await step.ready(c)
                if unready is not None:
                    items.append(
                        QueueItem(
                            type="decide", case_id=case.id, reference=case.reference,
                            workflow=case.workflow, case_title=case.title,
                            step_key=unready.fix_step or step.key,
                            step_title=f"Fix before the agent runs: {unready.message}",
                            kind=StepKind.PERSON, waiting_since=case.updated_at,
                        )
                    )  # fmt: skip
                    continue
            if problem is None:
                items.append(
                    QueueItem(
                        type="run" if step.kind == StepKind.AGENT else "decide",
                        case_id=case.id,
                        reference=case.reference,
                        workflow=case.workflow,
                        case_title=case.title,
                        step_key=step.key,
                        step_title=step.title,
                        kind=step.kind,
                        waiting_since=case.updated_at,
                    )
                )
    items.extend(await _other_work(session, access, open_cases))
    order = {"decide": 0, "review": 1, "mail": 2, "post": 3, "verify": 4, "run": 5}
    items.sort(key=lambda i: (order[i.type], i.waiting_since))
    return items


async def _other_work(
    session: AsyncSession, access: PodAccess, cases: list[PodCase]
) -> list[QueueItem]:
    """Drafted mail the viewer sends, ERP postings they post or verify, and open review
    tasks on the cases they see."""
    if not cases:
        return []
    by_id = {c.id: c for c in cases}
    ids = list(by_id)
    out: list[QueueItem] = []

    def item(case: PodCase, type_: QueueType, key: str, title: str, since: datetime) -> QueueItem:
        return QueueItem(type=type_, case_id=case.id, reference=case.reference,
                         workflow=case.workflow, case_title=case.title, step_key=key,
                         step_title=title, waiting_since=since)  # fmt: skip

    drafts = await session.scalars(
        select(PodMessage).where(
            PodMessage.case_id.in_(ids), PodMessage.status == MessageStatus.DRAFT
        )
    )
    for m in drafts:
        case = by_id[m.case_id]
        senders = WORKFLOWS[case.workflow].plan.senders.get(m.purpose, frozenset())
        if access.holds_any(set(senders), case.entity_id):
            out.append(item(case, "mail", m.purpose, f"Read and send: {m.subject}", m.created_at))
    postings = await session.scalars(
        select(PodPostingTask).where(
            PodPostingTask.case_id.in_(ids),
            PodPostingTask.status.in_([TaskStatus.PROPOSED, TaskStatus.RECORDED_UNVERIFIED]),
        )
    )
    for t in postings:
        case = by_id[t.case_id]
        posters = WORKFLOWS[case.workflow].plan.posters.get(t.kind.value, frozenset())
        if not access.holds_any(set(posters), case.entity_id):
            continue
        what = t.kind.value.removeprefix("create_").replace("_", " ")
        if t.status == TaskStatus.PROPOSED:
            out.append(item(case, "post", t.kind.value, f"Post the {what} to ERPNext",
                            t.created_at))  # fmt: skip
        else:
            out.append(item(case, "verify", t.kind.value,
                            f"Verify the {what} {t.external_txn_id or ''} on a fresh snapshot",
                            t.created_at))  # fmt: skip
    reviews = await session.scalars(
        select(PodReviewTask).where(
            PodReviewTask.case_id.in_(ids), PodReviewTask.status == ReviewTaskStatus.OPEN
        )
    )
    for r in reviews:
        out.append(item(by_id[r.case_id], "review", "review", r.subject or "Review task",
                        r.created_at))  # fmt: skip
    return out
