"""The step engine: L4/L5 steps of a case, in the requirement's order.

Every L5 row exists from the moment the case opens. A step is completed by a person holding
its capacity (PERSON / MANUAL), run by its agent handler (AGENT) or recorded by the system
(SYSTEM); one that doesn't apply is settled as not_applicable with its reason. Order
(`after`), capacity and segregation of duties (`distinct_from`) are checked here, so no
workflow can forget them. The case engine adds the actions and the approval blocker.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.service_pod.common.people import DELETED, names
from src.app.service_pod.core.cases.exceptions import CaseActionError, InvalidActionPayloadError
from src.app.service_pod.core.cases.models import CaseStatus
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.schemas import L5Out, NeedsFix, StepOut
from src.app.service_pod.core.steps.spec import (
    OWNER,
    SETTLED,
    L5Spec,
    StepFailedError,
    StepKind,
    StepPlan,
    StepSpec,
    StepStatus,
)
from src.app.service_pod.core.workflows import WORKFLOWS

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.models import PodCase
    from src.app.service_pod.core.cases.service import Ctx

MAX_LISTED = 3  # steps named in a blocker message


def plan_of(case: PodCase) -> StepPlan:
    return WORKFLOWS[case.workflow].plan


def has_steps(case: PodCase) -> bool:
    return bool(plan_of(case).steps)


async def create_steps(session: AsyncSession, case: PodCase) -> None:
    """One pending row per declared L5, when the case opens."""
    for step in plan_of(case).steps:
        for l5 in step.l5:
            session.add(PodCaseStep(case_id=case.id, step_key=step.key, l5_code=l5.code))


async def load_steps(session: AsyncSession, case: PodCase) -> list[PodCaseStep]:
    rows = list(await session.scalars(select(PodCaseStep).where(PodCaseStep.case_id == case.id)))
    order = {l5.code: i for i, l5 in enumerate(l5 for s in plan_of(case).steps for l5 in s.l5)}
    return sorted(rows, key=lambda r: order.get(r.l5_code, len(order)))


def fingerprint_part(case: PodCase, rows: list[PodCaseStep]) -> list[list[Any]]:
    """What an approval binds of the steps: their outcome, not who or when. Steps that run
    after the release (e.g. sending the approved PO) aren't part of what was approved."""
    later = {s.key for s in plan_of(case).steps if s.after_approval}
    return [[r.l5_code, r.status, r.result, r.note] for r in rows if r.step_key not in later]


def _rows_of(rows: list[PodCaseStep], key: str) -> list[PodCaseStep]:
    return [r for r in rows if r.step_key == key]


def status_of(rows: list[PodCaseStep], key: str) -> StepStatus:
    """A step's status from its L5 rows: failed if any failed, settled once all are."""
    mine = _rows_of(rows, key)
    if not mine:
        return StepStatus.PENDING
    if any(r.status == StepStatus.FAILED for r in mine):
        return StepStatus.FAILED
    if all(r.status == StepStatus.NOT_APPLICABLE for r in mine):
        return StepStatus.NOT_APPLICABLE
    if all(r.status in SETTLED for r in mine):
        return StepStatus.DONE
    return StepStatus.PENDING


def _settled(rows: list[PodCaseStep], key: str) -> bool:
    return status_of(rows, key) in SETTLED


def blockers(case: PodCase, rows: list[PodCaseStep], *, after_approval: bool = False) -> list[str]:
    """Why the case can't be approved yet (after_approval: completed yet) as far as its
    steps go."""
    plan = [s for s in plan_of(case).steps if s.after_approval == after_approval]
    failed = [s for s in plan if status_of(rows, s.key) == StepStatus.FAILED]
    pending = [s for s in plan if status_of(rows, s.key) == StepStatus.PENDING]
    problems = []
    if failed:
        problems.append(f"Failed step(s) must be redone: {_names(failed)}.")
    if pending:
        problems.append(f"{len(pending)} step(s) not done yet: {_names(pending)}.")
    return problems


def _names(steps: list[StepSpec]) -> str:
    listed = ", ".join(f"{s.key} {s.title}" for s in steps[:MAX_LISTED])
    more = len(steps) - MAX_LISTED
    return listed + (f" and {more} more" if more > 0 else "")


def current_step(case: PodCase, rows: list[PodCaseStep]) -> str | None:
    """The first step in the declared order that isn't settled (None: all are)."""
    return next((s.key for s in plan_of(case).steps if not _settled(rows, s.key)), None)


def _dependents(plan: StepPlan, key: str) -> list[StepSpec]:
    """Steps that (directly or through others) come after `key`."""
    found: list[StepSpec] = []
    frontier = {key}
    while frontier:
        nxt = [s for s in plan.steps if set(s.after) & frontier and s not in found]
        found.extend(nxt)
        frontier = {s.key for s in nxt}
    return found


# --- who may act --------------------------------------------------------------------------


def _order_problem(rows: list[PodCaseStep], step: StepSpec) -> str | None:
    waiting = [k for k in step.after if not _settled(rows, k)]
    if waiting:
        return f"Step {step.key} waits on {', '.join(waiting)}."
    return None


def _sod_problem(c: Ctx, step: StepSpec, user_id: uuid.UUID) -> str | None:
    for other in step.distinct_from:
        if other == OWNER:
            if c.case.owner_id == user_id:
                return f"Step {step.key} must be done by someone other than who opened the case."
        elif any(r.done_by == user_id for r in _rows_of(c.children.steps, other)):
            return f"Step {step.key} must be done by someone other than whoever did {other}."
    return None


def sod_problem(c: Ctx, step: StepSpec, user_id: uuid.UUID) -> str | None:
    """Why segregation of duties keeps this person from the step (None: it doesn't)."""
    return _sod_problem(c, step, user_id)


def _phase_problem(c: Ctx, step: StepSpec) -> str | None:
    approved = c.case.status == CaseStatus.APPROVED
    if step.after_approval and not approved:
        return f"Step {step.key} runs once the case is released."
    if not step.after_approval and approved:
        return "The case is released; send a step back to change what was approved."
    return None


def person_problem(c: Ctx, step: StepSpec) -> str | None:
    """Why the current user can't complete this PERSON / MANUAL step now (None: they can)."""
    if step.kind not in (StepKind.PERSON, StepKind.MANUAL):
        return f"Step {step.key} isn't done by a person."
    if _settled(c.children.steps, step.key):
        return f"Step {step.key} is already done; redo it to change it."
    if problem := _phase_problem(c, step):
        return problem
    if step.capacity and not c.access.holds(step.capacity, c.case.entity_id):
        return f"Step {step.key} needs the {step.capacity.replace('_', ' ')} capacity."
    return _order_problem(c.children.steps, step) or _sod_problem(c, step, c.user.id)


def agent_problem(c: Ctx, step: StepSpec) -> str | None:
    if step.kind != StepKind.AGENT or step.handler is None:
        return f"Step {step.key} isn't run by an agent."
    if _settled(c.children.steps, step.key):
        return f"Step {step.key} is already done; redo it to run it again."
    if problem := _phase_problem(c, step):
        return problem
    if not _may_drive(c, step):
        return "Only someone working on this case can run its agents."
    return _order_problem(c.children.steps, step)


def _may_drive(c: Ctx, step: StepSpec) -> bool:
    """An agent or redo is started by someone with a stake in it: the case's owner, a
    holder of the step's capacity, or a holder of a capacity of a later step."""
    if c.access.is_admin or c.case.owner_id == c.user.id:
        return True
    caps = {step.capacity, *step.run_by} | {
        s.capacity for s in _dependents(plan_of(c.case), step.key)
    }
    return c.access.holds_any({x for x in caps if x}, c.case.entity_id)


# --- payloads and handlers (wired into the case engine's ACTIONS) --------------------------


class CompleteStepPayload(BaseModel):
    step: str = Field(min_length=1, max_length=32)
    # L5 code -> its result fields (validated against the L5's declared model)
    results: dict[str, dict[str, Any]] = {}
    # A person's finding that the step fails (e.g. the bank call-back didn't confirm)
    failed_reason: str | None = Field(default=None, min_length=1, max_length=2000)


class RunAgentStepPayload(BaseModel):
    step: str = Field(min_length=1, max_length=32)


class RedoStepPayload(BaseModel):
    step: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)


def _spec(c: Ctx, key: str) -> StepSpec:
    step = plan_of(c.case).step(key)
    if step is None:
        raise InvalidActionPayloadError(f"Unknown step {key!r}.")
    return step


def _readable(l5: L5Spec, exc: ValidationError) -> str:
    """The first problem in the words the form shows: the field's title (and the row of a
    list), then what's wrong, e.g. "Trade references, row 2, Contact email: not a valid
    email address"."""
    first = exc.errors()[0]
    props = l5.result.model_json_schema().get("properties", {})
    parts: list[str] = []
    for i, part in enumerate(first["loc"]):
        if isinstance(part, int):
            parts.append(f"row {part + 1}")
        elif i == 0 and part in props:
            parts.append(str(props[part].get("title") or part))
        else:
            parts.append(str(part).replace("_", " ").capitalize())
    where = ", ".join(parts) or l5.text
    message = str(first["msg"]).removeprefix("Value error, ")
    return f"{where}: {message[0].lower()}{message[1:]}" if message else where


def _validated(step: StepSpec, results: dict[str, dict[str, Any]]) -> dict[str, BaseModel]:
    unknown = set(results) - {l5.code for l5 in step.l5}
    if unknown:
        raise InvalidActionPayloadError(
            f"{', '.join(sorted(unknown))} isn't part of step {step.key}."
        )
    out = {}
    for l5 in step.l5:
        try:
            out[l5.code] = l5.result.model_validate(results.get(l5.code, {}))
        except ValidationError as exc:
            raise InvalidActionPayloadError(_readable(l5, exc)) from exc
    return out


def _settle(
    rows: list[PodCaseStep],
    step: StepSpec,
    results: dict[str, BaseModel] | None,
    status: StepStatus,
    note: str | None,
    user_id: uuid.UUID | None,
) -> None:
    now = utcnow()
    for r in _rows_of(rows, step.key):
        r.status = status
        r.result = results[r.l5_code].model_dump(mode="json") if results else None
        r.note = note
        r.done_by = user_id
        r.done_at = now


async def settle_not_applicable(c: Ctx) -> list[str]:
    """Record as not_applicable every reachable pending step whose rule says it doesn't
    apply (with that reason), repeating while that unblocks further steps."""
    settled: list[str] = []
    progress = True
    while progress:
        progress = False
        for step in plan_of(c.case).steps:
            rows = c.children.steps
            if step.not_applicable_when is None or _settled(rows, step.key):
                continue
            if status_of(rows, step.key) == StepStatus.FAILED or _order_problem(rows, step):
                continue
            reason = await step.not_applicable_when(c)
            if reason:
                _settle(rows, step, None, StepStatus.NOT_APPLICABLE, reason, None)
                settled.append(step.key)
                progress = True
    return settled


async def complete_step(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, CompleteStepPayload)  # noqa: S101 - dispatch guarantees the type
    step = _spec(c, p.step)
    if problem := person_problem(c, step):
        raise CaseActionError(problem)
    changed = not step.after_approval
    if p.failed_reason:
        _settle(c.children.steps, step, None, StepStatus.FAILED, p.failed_reason, c.user.id)
        return f"Step {step.key} {step.title}: failed ({p.failed_reason})", changed
    _settle(c.children.steps, step, _validated(step, p.results), StepStatus.DONE, None, c.user.id)
    reaction = await step.on_done(c, step) if step.on_done else None
    skipped = await settle_not_applicable(c)
    summary = f"Step {step.key} {step.title}: done" + (f"; {reaction}" if reaction else "")
    return summary + _skipped(skipped), changed


async def run_agent_step(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, RunAgentStepPayload)  # noqa: S101
    step = _spec(c, p.step)
    if problem := agent_problem(c, step):
        raise CaseActionError(problem)
    assert step.handler is not None  # noqa: S101 - agent_problem checked it
    if step.ready is not None and (unready := await step.ready(c)) is not None:
        fix = plan_of(c.case).step(unready.fix_step) if unready.fix_step else None
        where = f" Fix it in step {fix.key} ({fix.title}) first." if fix else ""
        raise CaseActionError(f"The agent can't run yet: {unready.message}{where}")
    try:
        produced = await step.handler(c, step)
        expected = {l5.code: l5.result for l5 in step.l5}
        if set(produced) != set(expected) or any(
            not isinstance(produced[code], model) for code, model in expected.items()
        ):
            raise StepFailedError("The agent's output doesn't match the step's declared results.")
    except StepFailedError as exc:
        _settle(c.children.steps, step, None, StepStatus.FAILED, str(exc), None)
        return (
            f"Step {step.key} {step.title}: the agent couldn't finish ({exc})",
            not step.after_approval,
        )
    _settle(c.children.steps, step, produced, StepStatus.DONE, None, None)
    reaction = await step.on_done(c, step) if step.on_done else None
    skipped = await settle_not_applicable(c)
    summary = f"Step {step.key} {step.title}: run by the agent" + (
        f"; {reaction}" if reaction else ""
    )
    return summary + _skipped(skipped), not step.after_approval


async def redo_step(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    """Send a step (and every step after it) back to pending, e.g. a budget owner's query
    returns the request to its requester. Each redo counts as rework."""
    assert isinstance(p, RedoStepPayload)  # noqa: S101
    step = _spec(c, p.step)
    if status_of(c.children.steps, step.key) == StepStatus.PENDING:
        raise CaseActionError(f"Step {step.key} isn't done yet.")
    if not _may_drive(c, step):
        raise CaseActionError("Only someone working on this case can send a step back.")
    skipped = await send_back(c, step.key, p.reason)
    summary = f"Step {step.key} {step.title} sent back: {p.reason}" + _skipped(skipped)
    # Sending back a step that runs after the release changes nothing that was approved
    return summary, not (step.after_approval and c.case.status == CaseStatus.APPROVED)


async def send_back(c: Ctx, key: str, reason: str) -> list[str]:
    """Reset a step and every step after it to pending (rework, counted by the measures);
    returns the steps that then turned out not to apply."""
    step = _spec(c, key)
    reset = [step, *_dependents(plan_of(c.case), step.key)]
    if c.case.status == CaseStatus.APPROVED and step.after_approval:
        reset = [s for s in reset if s.after_approval]
    # What the sent-back step held, so its form starts from it
    previous = {r.l5_code: r.result for r in _rows_of(c.children.steps, step.key) if r.result}
    if previous:
        c.case.state = {**c.case.state, "_previous": {**c.case.state.get("_previous", {}),
                                                      **previous}}  # fmt: skip
    for s in reset:
        for r in _rows_of(c.children.steps, s.key):
            r.status, r.result, r.note, r.done_by, r.done_at = (
                StepStatus.PENDING, None, None, None, None,
            )  # fmt: skip
    # The person who fills it in again sees why it came back
    for r in _rows_of(c.children.steps, step.key):
        r.note = f"Sent back: {reason}"
    if c.request is not None:
        record_event(
            c.session,
            "finance.step_sent_back",
            c.request,
            actor_id=c.user.id,
            run=c.case.reference,
            case_id=str(c.case.id),
            step=step.key,
            reason=reason,
            summary=f"{c.case.reference}: step {step.key} sent back ({reason})",
        )
    return await settle_not_applicable(c)


def _skipped(keys: list[str]) -> str:
    return f" (not applicable: {', '.join(keys)})" if keys else ""


async def record_system_step(
    c: Ctx, key: str, results: dict[str, BaseModel], *, failed: str | None = None
) -> None:
    """For a flow's own code: a SYSTEM step happened (e.g. the posting was verified)."""
    step = _spec(c, key)
    if step.kind != StepKind.SYSTEM:
        raise CaseActionError(f"Step {step.key} isn't a system event.")
    if failed:
        _settle(c.children.steps, step, None, StepStatus.FAILED, failed, None)
        return
    checked = _validated(step, {code: r.model_dump(mode="json") for code, r in results.items()})
    _settle(c.children.steps, step, checked, StepStatus.DONE, None, None)
    await settle_not_applicable(c)


# --- what the screens get -----------------------------------------------------------------


async def outs(c: Ctx) -> list[StepOut]:
    rows = c.children.steps
    people = await names(c.session, (r.done_by for r in rows))
    previous = c.case.state.get("_previous", {})
    out = []
    for step in plan_of(c.case).steps:
        mine = {r.l5_code: r for r in _rows_of(rows, step.key)}
        if c.locked:
            blocked: str | None = f"The case is {c.case.status.value}."
        elif step.kind == StepKind.AGENT:
            blocked = agent_problem(c, step)
        elif step.kind == StepKind.SYSTEM:
            blocked = "Recorded by the system."
        else:
            blocked = person_problem(c, step)
        needs = None
        if not c.locked and step.kind == StepKind.AGENT and step.ready is not None:
            settled = _settled(rows, step.key)
            waiting = _order_problem(rows, step) is not None
            if not settled and not waiting and (unready := await step.ready(c)) is not None:
                fix = plan_of(c.case).step(unready.fix_step) if unready.fix_step else None
                needs = NeedsFix(message=unready.message, fix_step=fix.key if fix else None,
                                 fix_title=fix.title if fix else None)  # fmt: skip
                blocked = f"Can't run yet: {unready.message}"
        out.append(
            StepOut(
                key=step.key,
                l4=step.l4,
                title=step.title,
                kind=step.kind,
                capacity=step.capacity,
                after=list(step.after),
                status=status_of(rows, step.key),
                blocked=blocked,
                needs=needs,
                l5=[
                    L5Out(
                        code=l5.code,
                        text=l5.text,
                        status=mine[l5.code].status if l5.code in mine else StepStatus.PENDING,
                        result=mine[l5.code].result if l5.code in mine else None,
                        note=mine[l5.code].note if l5.code in mine else None,
                        done_by=_who(people, step.kind, mine.get(l5.code)),
                        done_at=mine[l5.code].done_at if l5.code in mine else None,
                        result_schema=l5.result.model_json_schema(),
                        previous=previous.get(l5.code)
                        if (mine[l5.code].status if l5.code in mine else StepStatus.PENDING)
                        == StepStatus.PENDING
                        else None,
                    )
                    for l5 in step.l5
                ],
            )
        )
    return out


def _who(people: dict[uuid.UUID, str], kind: StepKind, row: PodCaseStep | None) -> str | None:
    if row is None or row.done_at is None:
        return None
    if row.done_by is None:
        if kind in (StepKind.PERSON, StepKind.MANUAL) and row.status == StepStatus.DONE:
            return "Through the portal"  # an outside party (e.g. a client applying)
        agent = kind == StepKind.AGENT and row.status != StepStatus.NOT_APPLICABLE
        return "Agent" if agent else "System"
    return people.get(row.done_by, DELETED)
