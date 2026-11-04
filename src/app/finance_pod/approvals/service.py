"""Budget check and approval (Phase 1.2): the budget agent's check on submission, then each
step of the route decided in order by its approver.

Who may decide a step: the Finance Admin whose email the route names; if that person has no
account, any other Finance Admin, recorded as deciding for them. Never the requester, and
never the same admin for two steps of one round, unless self-approval is allowed (then the
decision is marked). Approving needs no blocking finding; over budget, no budget line or an
uncategorised grant line needs `acknowledge_budget` and a note. The last approval holds the
budget (commitments) and approves the request.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.finance_pod.access import (
    FinanceAccess,
    SeparationOfDutiesError,
    check_different_person,
)
from src.app.finance_pod.approvals import budget_agent
from src.app.finance_pod.approvals.models import Decision, FpCommitment, FpDecision
from src.app.finance_pod.approvals.schemas import BudgetCheck, DecisionOut, RouteStep
from src.app.finance_pod.requests.exceptions import (
    RequestInvalidError,
    RequestLockedError,
    RequestNotFoundError,
    StaleRequestError,
)
from src.app.finance_pod.requests.models import FpPurchaseRequest, RequestStatus
from src.app.finance_pod.settings.service import current as current_settings
from src.app.finance_pod.sourcing import service as sourcing


async def run_check(session: AsyncSession, request: FpPurchaseRequest) -> BudgetCheck:
    result = await budget_agent.check(session, request)
    request.budget_check = result.model_dump(mode="json")
    return result


async def decisions_of(
    session: AsyncSession, request: FpPurchaseRequest, *, this_round: bool
) -> list[FpDecision]:
    query = select(FpDecision).where(FpDecision.request_id == request.id)
    if this_round:
        query = query.where(FpDecision.round == request.round)
    return list(await session.scalars(query.order_by(FpDecision.created_at)))


def route_status(check: BudgetCheck, decisions: list[FpDecision]) -> list[RouteStep]:
    """The route with each step's status in the current round."""
    by_step = {d.step: d for d in decisions}
    waiting_set = False
    steps = []
    for s in check.route:
        d = by_step.get(s.step)
        if d is not None:
            status = {
                Decision.APPROVE: "approved",
                Decision.REJECT: "rejected",
                Decision.QUERY: "queried",
            }[d.decision]
        elif not waiting_set and not any(x.decision != Decision.APPROVE for x in decisions):
            status, waiting_set = "waiting", True
        else:
            status = "pending"
        steps.append(s.model_copy(update={"status": status}))
    return steps


@dataclass(frozen=True)
class DecideView:
    check: BudgetCheck | None
    route: list[RouteStep]
    current: RouteStep | None
    blocker: str | None  # why the viewer can't decide now (None: they can)
    decisions: list[DecisionOut]


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return dict(rows.all())


async def _blocker(
    session: AsyncSession,
    request: FpPurchaseRequest,
    current: RouteStep | None,
    decisions: list[FpDecision],
    viewer: User,
) -> str | None:
    if request.status != RequestStatus.SUBMITTED:
        return f"{request.reference} isn't waiting for a decision."
    if current is None:
        return "Nothing to decide."
    named = (current.approver_email or "").lower()
    if current.approver_name is not None and viewer.email.lower() != named:
        return f"Waiting for {current.approver_name} ({current.capacity})."
    self_ok = (await current_settings(session)).allow_self_approval
    if viewer.id == request.requester_id and not self_ok:
        return "You raised this request, so a different Finance Admin has to decide it."
    if any(d.decided_by == viewer.id for d in decisions) and not self_ok:
        return "You already decided a step of this request; another Finance Admin decides this one."
    return None


async def view(session: AsyncSession, request: FpPurchaseRequest, viewer: User) -> DecideView:
    all_decisions = await decisions_of(session, request, this_round=False)
    names = await _names(session, {d.decided_by for d in all_decisions})
    out = [
        DecisionOut(
            id=d.id,
            round=d.round,
            step=d.step,
            capacity=d.capacity,
            approver_email=d.approver_email,
            decided_by_name=names.get(d.decided_by, "a deleted user"),
            decision=d.decision,
            note=d.note,
            acting_for=d.acting_for,
            budget_acknowledged=d.budget_acknowledged,
            self_approval=d.self_approval,
            created_at=d.created_at,
        )
        for d in all_decisions
    ]
    if not request.budget_check:
        return DecideView(None, [], None, "Not submitted yet.", out)
    check = BudgetCheck.model_validate(request.budget_check)
    current_round = [d for d in all_decisions if d.round == request.round]
    route = route_status(check, current_round)
    current = next((s for s in route if s.status == "waiting"), None)
    blocker = await _blocker(session, request, current, current_round, viewer)
    return DecideView(check, route, current, blocker, out)


async def decide(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    version: int,
    decision: Decision,
    note: str,
    acknowledge_budget: bool,
    ctx: RequestContext,
) -> FpPurchaseRequest:
    request = await session.get(FpPurchaseRequest, request_id, with_for_update=True)
    if request is None:
        raise RequestNotFoundError
    if request.version != version:
        raise StaleRequestError
    if request.status != RequestStatus.SUBMITTED or not request.budget_check:
        raise RequestLockedError(f"{request.reference} isn't waiting for a decision.")
    actor = access.user
    note = note.strip()
    current_round = await decisions_of(session, request, this_round=True)
    check = BudgetCheck.model_validate(request.budget_check)
    route = route_status(check, current_round)
    current = next((s for s in route if s.status == "waiting"), None)
    if current is None:
        raise RequestLockedError("Nothing to decide on this request.")

    named = current.approver_email
    acting_for = None
    if current.approver_name is not None:
        if actor.email.lower() != (named or "").lower():
            raise SeparationOfDutiesError(
                f"This step waits for {current.approver_name} ({current.capacity})."
            )
    else:
        acting_for = named
    self_approval = await check_different_person(
        session, actor, request.requester_id, "Nobody approves a request they raised."
    )
    earlier = next((d for d in current_round if d.decided_by == actor.id), None)
    if earlier is not None:
        self_approval = (
            await check_different_person(
                session, actor, earlier.decided_by, "One person can't decide two steps."
            )
            or self_approval
        )

    if decision in (Decision.REJECT, Decision.QUERY) and not note:
        raise RequestInvalidError(
            "Say why you reject it." if decision == Decision.REJECT else "Write your question."
        )
    acknowledged = False
    if decision == Decision.APPROVE:
        blocking = [f.message for f in check.findings if f.severity == "blocking"]
        if blocking:
            raise RequestInvalidError(
                "The budget check blocks approval: "
                + " ".join(blocking)
                + " Reject it or query the requester."
            )
        to_ack = [f.message for f in check.findings if f.severity == "acknowledge"]
        if to_ack:
            if not acknowledge_budget or not note:
                raise RequestInvalidError(
                    "Confirm you approve despite: " + " ".join(to_ack) + " and say why in a note."
                )
            acknowledged = True

    session.add(
        FpDecision(
            request_id=request.id,
            round=request.round,
            step=current.step,
            capacity=current.capacity,
            approver_email=named,
            decided_by=actor.id,
            decision=decision,
            note=note,
            acting_for=acting_for,
            budget_acknowledged=acknowledged,
            self_approval=self_approval,
        )
    )
    request.version += 1
    last = current.step == len(route)
    if decision == Decision.APPROVE and last:
        request.status = RequestStatus.APPROVED
        request.approved_at = utcnow()
        await sourcing.start(session, request)  # the sourcing agent takes over (1.3)
        for impact in check.impacts:
            if impact.budget_id is not None and impact.this_request > 0:
                session.add(
                    FpCommitment(
                        request_id=request.id,
                        budget_id=impact.budget_id,
                        amount=impact.this_request,
                    )
                )
    elif decision == Decision.REJECT:
        request.status = RequestStatus.REJECTED
        request.closed_at = utcnow()
    elif decision == Decision.QUERY:
        request.status = RequestStatus.QUERIED

    event, verb = {
        Decision.APPROVE: (
            ("fpod.request_approved", "Approved")
            if last
            else ("fpod.request_step_approved", "Approved a step of")
        ),
        Decision.REJECT: ("fpod.request_rejected", "Rejected"),
        Decision.QUERY: ("fpod.request_queried", "Queried the requester on"),
    }[decision]
    record_event(
        session,
        event,
        ctx,
        actor_id=actor.id,
        run=request.reference,
        request_id=str(request.id),
        step=current.step,
        capacity=current.capacity,
        acting_for=acting_for,
        budget_acknowledged=acknowledged,
        self_approval=self_approval,
        note=note,
        summary=(
            f"{verb} purchase request {request.reference} as {current.capacity}"
            + (f" for {acting_for}" if acting_for else "")
            + (" (own request: self-approval allowed)" if self_approval else "")
            + (f": {note}" if note else "")
        ),
    )
    await session.commit()
    return request


async def recheck(
    session: AsyncSession, access: FinanceAccess, request_id: uuid.UUID, ctx: RequestContext
) -> FpPurchaseRequest:
    """Run the budget agent again (e.g. after new budgets were loaded), before any decision."""
    request = await session.get(FpPurchaseRequest, request_id, with_for_update=True)
    if request is None:
        raise RequestNotFoundError
    if request.status != RequestStatus.SUBMITTED:
        raise RequestLockedError(f"{request.reference} isn't waiting for a decision.")
    if await decisions_of(session, request, this_round=True):
        raise RequestLockedError(
            "A step is already decided on this check; query the requester to start again."
        )
    await run_check(session, request)
    request.version += 1
    record_event(
        session,
        "fpod.budget_rechecked",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        request_id=str(request.id),
        summary=f"Budget agent re-checked {request.reference}",
    )
    await session.commit()
    return request


async def release_commitments(
    session: AsyncSession, request: FpPurchaseRequest, reason: str
) -> None:
    for c in await session.scalars(
        select(FpCommitment).where(
            FpCommitment.request_id == request.id, FpCommitment.released_at.is_(None)
        )
    ):
        c.released_at = utcnow()
        c.release_reason = reason[:200]


async def waiting_for(session: AsyncSession, viewer: User) -> list[uuid.UUID]:
    """Requests whose current step the viewer can decide now."""
    ids = []
    for request in await session.scalars(
        select(FpPurchaseRequest)
        .where(FpPurchaseRequest.status == RequestStatus.SUBMITTED)
        .order_by(FpPurchaseRequest.submitted_at)
    ):
        v = await view(session, request, viewer)
        if v.blocker is None:
            ids.append(request.id)
    return ids
