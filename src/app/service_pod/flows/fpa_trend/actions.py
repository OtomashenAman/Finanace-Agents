"""FP&A case actions beyond the engine's: commentary written by a person, the account
mapping review, and manual corrections (proposed, withdrawn, queued for posting)."""

from decimal import Decimal

from pydantic import BaseModel

from src.app.common.clock import utcnow
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases.exceptions import CaseActionError, InvalidActionPayloadError
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.cases.service import DRAFT, ActionSpec, Ctx, need_status
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import AccountClass
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import TaskKind
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.flows.fpa_trend.schemas import (
    ConfirmMappingPayload,
    CorrectionRef,
    ProposeCorrectionPayload,
    SetCommentaryPayload,
)
from src.app.service_pod.flows.fpa_trend.service import (
    correction_reference,
    correction_tasks,
    facts,
)

OPERATING = {AccountClass.INCOME, AccountClass.COST_OF_GOODS_SOLD, AccountClass.EXPENSE}


def _draft(doing: str):  # type: ignore[no-untyped-def]
    return lambda c: need_status(c, DRAFT, doing)


def _set_state(case: PodCase, **changes: object) -> None:
    case.state = plain({**case.state, **changes})


async def _set_commentary(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, SetCommentaryPayload)  # noqa: S101
    known = {f.id for f in facts(c.case.state)}
    for i, h in enumerate(p.highlights, start=1):
        unknown = [f for f in h.fact_ids if f not in known]
        if unknown:
            raise InvalidActionPayloadError(f"Line {i} cites unknown facts: {', '.join(unknown)}.")
    _set_state(
        c.case,
        commentary={
            "by": "hand",
            "author": c.user.full_name,
            "written_at": utcnow(),
            "highlights": [h.model_dump() for h in p.highlights],
            "facts": [vars(f) for f in facts(c.case.state)],
        },
    )
    return "Wrote the commentary by hand", True


async def _confirm_mapping(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, ConfirmMappingPayload)  # noqa: S101
    _set_state(
        c.case,
        mapping_review={
            "by": c.user.full_name,
            "at": utcnow(),
            "note": (p.note or "").strip() or None,
            "accounts": len(c.case.state.get("mapping", [])),
        },
    )
    return "Reviewed the account mapping", True


async def _propose_correction(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, ProposeCorrectionPayload)  # noqa: S101
    months = c.case.state.get("months", [])
    if not months or p.period != months[-1]:
        raise InvalidActionPayloadError(
            f"A correction is for the current period ({months[-1] if months else '-'}) only."
        )
    snapshot = await c.session.get(PodSnapshot, c.case.snapshot_id)
    assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
    doc = snapshots.document(snapshot)
    evidence = next((g for g in doc.gl_lines or [] if g.id == p.evidence_gl_line_id), None)
    if evidence is None or evidence.period != p.period:
        raise InvalidActionPayloadError(
            f"The evidence must be a GL line of {p.period} in the case's source."
        )
    accounts = {a.id: a for a in doc.accounts or []}
    unknown = [line.account_id for line in p.lines if line.account_id not in accounts]
    if unknown:
        raise InvalidActionPayloadError(f"Unknown accounts: {', '.join(unknown)}.")
    if not any(accounts[line.account_id].classification in OPERATING for line in p.lines):
        raise InvalidActionPayloadError(
            "A correction must touch a mapped income, cost of services or expense account."
        )
    debit = sum((line.debit for line in p.lines), Decimal(0))
    credit = sum((line.credit for line in p.lines), Decimal(0))
    if debit != credit:
        raise InvalidActionPayloadError(f"Debits {debit} and credits {credit} must balance.")
    existing = c.case.state.get("corrections", [])
    correction = {
        "id": f"C{len(existing) + 1}",
        "status": "proposed",
        "period": p.period,
        "evidence_gl_line_id": evidence.id,
        "rationale": p.rationale.strip(),
        "lines": [line.model_dump() for line in p.lines],
        "proposed_by": c.user.full_name,
        "proposed_at": utcnow(),
    }
    _set_state(c.case, corrections=[*existing, correction])
    return f"Proposed correction {correction['id']} ({debit} balanced)", True


def _find(c: Ctx, correction_id: str) -> dict[str, object]:
    found = next((x for x in c.case.state.get("corrections", []) if x["id"] == correction_id), None)
    if found is None:
        raise InvalidActionPayloadError("Unknown correction.")
    return found  # type: ignore[no-any-return]


async def _withdraw_correction(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, CorrectionRef)  # noqa: S101
    target = _find(c, p.correction_id)
    queued = correction_reference(c.case, p.correction_id) in await correction_tasks(
        c.session, c.case
    )
    if target["status"] != "proposed" or queued:
        raise CaseActionError("Only a correction not yet queued for posting can be withdrawn.")
    _set_state(
        c.case,
        corrections=[
            {**x, "status": "withdrawn"} if x["id"] == p.correction_id else x
            for x in c.case.state.get("corrections", [])
        ],
    )
    return f"Withdrew correction {p.correction_id}", True


async def _queue_correction(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    """The signed-off correction goes to the Finance Admin to post in QuickBooks."""
    assert isinstance(p, CorrectionRef)  # noqa: S101
    target = _find(c, p.correction_id)
    if target["status"] != "proposed":
        raise CaseActionError(f"Correction {p.correction_id} is {target['status']}.")
    task = await tasks.add_task(
        c.session,
        c.case,
        TaskCreate(
            kind=TaskKind.JOURNAL_ENTRY,
            reference=correction_reference(c.case, p.correction_id),
            instructions={
                "period": target["period"],
                "lines": target["lines"],
                "rationale": target["rationale"],
                "evidence_gl_line_id": target["evidence_gl_line_id"],
            },
            note="Post this journal entry in QuickBooks exactly as listed, then record its ID.",
        ),
        c.user.id,
    )
    # The approved content doesn't change (the task is found by its reference)
    return f"Queued manual journal {task.reference} for the Finance Admin", False


ACTIONS = {
    "set_commentary": ActionSpec(
        SetCommentaryPayload, _draft("change the commentary"), _set_commentary
    ),
    "confirm_mapping": ActionSpec(
        ConfirmMappingPayload, _draft("review the mapping"), _confirm_mapping
    ),
    "propose_correction": ActionSpec(
        ProposeCorrectionPayload, _draft("propose a correction"), _propose_correction
    ),
    "withdraw_correction": ActionSpec(
        CorrectionRef, _draft("withdraw a correction"), _withdraw_correction
    ),
    "queue_correction": ActionSpec(
        CorrectionRef,
        lambda c: need_status(c, frozenset({CaseStatus.APPROVED}), "queue a correction"),
        _queue_correction,
    ),
}
