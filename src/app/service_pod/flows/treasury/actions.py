"""Treasury case actions: the Treasury Head's review of each imported tranche, and the
Optimistic / Stress shifts (parts of existing events moved to explicit dates)."""

from decimal import Decimal

from pydantic import BaseModel

from src.app.common.clock import utcnow
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases.exceptions import CaseActionError, InvalidActionPayloadError
from src.app.service_pod.core.cases.service import DRAFT, ActionSpec, Ctx, need_status
from src.app.service_pod.flows.treasury.schemas import (
    AddShiftPayload,
    RemoveShiftPayload,
    ReviewReceiptPayload,
)
from src.app.service_pod.flows.treasury.service import event_amount, recompute


def _draft(doing: str):  # type: ignore[no-untyped-def]
    return lambda c: need_status(c, DRAFT, doing)


async def _review_receipt(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, ReviewReceiptPayload)  # noqa: S101
    receipts = c.case.state.get("receipts", [])
    target = next((r for r in receipts if r["id"] == p.receipt_id), None)
    if target is None:
        raise InvalidActionPayloadError("Unknown receipt tranche.")
    if target.get("rejected"):
        raise CaseActionError(f"This tranche is rejected: {target['rejected']}")
    review = {
        "include": p.include,
        "probability": p.probability if p.include else Decimal(0),
        "rationale": (p.rationale or "").strip() or None,
        "by": c.user.full_name,
        "at": utcnow(),
    }
    c.case.state = plain(
        {
            **c.case.state,
            "receipts": [
                {**r, "review": review} if r["id"] == p.receipt_id else r for r in receipts
            ],
        }
    )
    recompute(c.case)
    what = f"included at {p.probability}" if p.include else "left out"
    return f"Reviewed {target['invoice_number']} {target['date']}: {what}", True


async def _add_shift(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, AddShiftPayload)  # noqa: S101
    event = event_amount(c.case.state, p.event_id)
    if event is None:
        raise InvalidActionPayloadError(
            "Shift an included receipt or an approved outflow of the base forecast."
        )
    kind, nominal, when = event
    scenarios = dict(c.case.state.get("scenarios") or {})
    shifts = list(scenarios.get(p.scenario, []))
    already = sum(
        (Decimal(str(s["amount"])) for s in shifts if s["event_id"] == p.event_id), Decimal(0)
    )
    if already + p.amount > nominal:
        raise InvalidActionPayloadError(
            f"At most {nominal - already} of this {kind} is left to move in this scenario."
        )
    if p.to_date == when:
        raise InvalidActionPayloadError("Move it to another date: the same date changes nothing.")
    shift = {
        "id": f"S{sum(len(v) for v in scenarios.values()) + 1}",
        "event_id": p.event_id,
        "kind": kind,
        "amount": p.amount,
        "from_date": when,
        "to_date": p.to_date,
        "note": p.note.strip(),
        "by": c.user.full_name,
    }
    scenarios[p.scenario] = [*shifts, shift]
    c.case.state = plain({**c.case.state, "scenarios": scenarios})
    recompute(c.case)
    return f"{p.scenario.title()}: moved {p.amount} of {p.event_id} to {p.to_date}", True


async def _remove_shift(c: Ctx, p: BaseModel) -> tuple[str, bool]:
    assert isinstance(p, RemoveShiftPayload)  # noqa: S101
    scenarios = dict(c.case.state.get("scenarios") or {})
    shifts = scenarios.get(p.scenario, [])
    if not any(s["id"] == p.shift_id for s in shifts):
        raise InvalidActionPayloadError("Unknown shift.")
    scenarios[p.scenario] = [s for s in shifts if s["id"] != p.shift_id]
    c.case.state = plain({**c.case.state, "scenarios": scenarios})
    recompute(c.case)
    return f"{p.scenario.title()}: removed shift {p.shift_id}", True


ACTIONS = {
    "review_receipt": ActionSpec(ReviewReceiptPayload, _draft("review a receipt"), _review_receipt),
    "add_shift": ActionSpec(AddShiftPayload, _draft("change a scenario"), _add_shift),
    "remove_shift": ActionSpec(RemoveShiftPayload, _draft("change a scenario"), _remove_shift),
}
