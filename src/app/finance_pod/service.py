"""Finance POD: capacities (granted by a Finance Admin), the viewer's own access, and the
dashboard (workflow tiles with the requirement's measures, and the steps waiting on me)."""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.entities import service as entities
from src.app.entities.models import LegalEntity
from src.app.finance_pod.capacities import LABELS, FinanceCapacity, label
from src.app.finance_pod.models import FinanceCapacityAssignment
from src.app.finance_pod.schemas import (
    AssignmentCreate,
    AssignmentOut,
    AssignmentPerson,
    CapacityOut,
    FinanceDashboard,
    FinanceMe,
    HeldCapacity,
    MeasureOut,
    QueueItem,
    WorkflowTile,
)
from src.app.service_pod.common.people import name_of, names
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import LOCKED_STATUSES, CaseStatus, PodCase
from src.app.service_pod.core.cases.service import case_context, visible_condition
from src.app.service_pod.core.steps import service as steps
from src.app.service_pod.core.steps.spec import StepKind
from src.app.service_pod.core.workflows import PodKey, workflows_in

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
        mine = [c for c in cases if c.workflow == spec.key]
        tiles.append(
            WorkflowTile(
                key=spec.key,
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
    return FinanceDashboard(workflows=tiles, my_queue=await _my_queue(session, access, cases))


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
            if problem is None:
                items.append(
                    QueueItem(
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
    return items
