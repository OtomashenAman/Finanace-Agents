"""Phase 1 measures: request-to-PO cycle time, where the time goes, and rework.

Cycle time runs from the request being raised to its PO being issued. Stage times use each
request's own timestamps (submitted, approved, vendor chosen, PO issued); a resubmitted
request's submission time is its last one. Rework: submitted requests that were queried
or resubmitted, out of all submitted.
"""

from collections import defaultdict
from datetime import datetime
from statistics import median

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.approvals.models import Decision, FpDecision
from src.app.finance_pod.orders.models import FpPurchaseOrder, PoStatus
from src.app.finance_pod.requests.models import FpPurchaseRequest, RequestStatus
from src.app.finance_pod.sourcing.models import FpSourcing, SourcingStatus


class Duration(BaseModel):
    label: str
    median_days: float | None
    count: int


class Waiting(BaseModel):
    stage: str
    count: int
    oldest_days: float | None


class MonthPoint(BaseModel):
    month: str  # YYYY-MM
    pos_issued: int
    median_cycle_days: float | None


class Measures(BaseModel):
    cycle: Duration  # request raised -> PO issued
    stages: list[Duration]
    submitted: int
    reworked: int
    rework_rate: float | None
    rejected: int
    waiting: list[Waiting]
    months: list[MonthPoint]


def _days(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None or b < a:
        return None
    return (b - a).total_seconds() / 86400


def _duration(label: str, values: list[float | None]) -> Duration:
    vals = [v for v in values if v is not None]
    return Duration(
        label=label, median_days=round(median(vals), 1) if vals else None, count=len(vals)
    )


async def measures(session: AsyncSession) -> Measures:
    now = utcnow()
    requests = list(await session.scalars(select(FpPurchaseRequest)))
    sourcing = {s.request_id: s for s in await session.scalars(select(FpSourcing))}
    pos = {
        p.request_id: p
        for p in await session.scalars(
            select(FpPurchaseOrder).where(FpPurchaseOrder.status != PoStatus.CANCELLED)
        )
    }
    queried = set(
        await session.scalars(
            select(FpDecision.request_id).where(FpDecision.decision == Decision.QUERY)
        )
    )

    cycle, s_sub, s_appr, s_choose, s_po = [], [], [], [], []
    by_month: dict[str, list[float]] = defaultdict(list)
    for r in requests:
        po = pos.get(r.id)
        src = sourcing.get(r.id)
        issued = po.issued_at if po else None
        c = _days(r.created_at, issued)
        cycle.append(c)
        if issued is not None and c is not None:
            by_month[issued.strftime("%Y-%m")].append(c)
        s_sub.append(_days(r.created_at, r.submitted_at))
        s_appr.append(_days(r.submitted_at, r.approved_at))
        s_choose.append(_days(r.approved_at, src.decided_at if src else None))
        s_po.append(_days(src.decided_at if src else None, issued))

    submitted = [r for r in requests if r.round >= 1]
    reworked = [r for r in submitted if r.round > 1 or r.id in queried]

    def oldest(items: list[datetime | None]) -> float | None:
        ages = [a for a in (_days(t, now) for t in items) if a is not None]
        return round(max(ages), 1) if ages else None

    by_status = defaultdict(list)
    for r in requests:
        by_status[r.status].append(r)
    approved = by_status[RequestStatus.APPROVED]
    no_vendor = [
        r
        for r in approved
        if (sourcing.get(r.id) is None or sourcing[r.id].status == SourcingStatus.OPEN)
    ]
    onboarding = [
        r
        for r in approved
        if sourcing.get(r.id) is not None
        and sourcing[r.id].status == SourcingStatus.AWAITING_VENDOR
    ]
    chosen_no_po = [
        r
        for r in approved
        if sourcing.get(r.id) is not None
        and sourcing[r.id].status == SourcingStatus.CHOSEN
        and r.id not in pos
    ]
    live_pos = list(pos.values())

    def po_waiting(status: PoStatus) -> list[FpPurchaseOrder]:
        return [p for p in live_pos if p.status == status]

    waiting = [
        Waiting(
            stage="Drafts (requester)",
            count=len(by_status[RequestStatus.DRAFT]),
            oldest_days=oldest([r.created_at for r in by_status[RequestStatus.DRAFT]]),
        ),
        Waiting(
            stage="Queried (requester)",
            count=len(by_status[RequestStatus.QUERIED]),
            oldest_days=oldest([r.updated_at for r in by_status[RequestStatus.QUERIED]]),
        ),
        Waiting(
            stage="Budget approval",
            count=len(by_status[RequestStatus.SUBMITTED]),
            oldest_days=oldest([r.submitted_at for r in by_status[RequestStatus.SUBMITTED]]),
        ),
        Waiting(
            stage="Sourcing (buyer)",
            count=len(no_vendor),
            oldest_days=oldest([r.approved_at for r in no_vendor]),
        ),
        Waiting(
            stage="Vendor onboarding",
            count=len(onboarding),
            oldest_days=oldest([sourcing[r.id].decided_at for r in onboarding]),
        ),
        Waiting(
            stage="PO to draft",
            count=len(chosen_no_po),
            oldest_days=oldest([sourcing[r.id].decided_at for r in chosen_no_po]),
        ),
        Waiting(
            stage="PO draft / approval",
            count=len(po_waiting(PoStatus.DRAFT))
            + len(po_waiting(PoStatus.PENDING_APPROVAL))
            + len(po_waiting(PoStatus.APPROVED)),
            oldest_days=oldest(
                [
                    p.created_at
                    for p in live_pos
                    if p.status in (PoStatus.DRAFT, PoStatus.PENDING_APPROVAL, PoStatus.APPROVED)
                ]
            ),
        ),
        Waiting(
            stage="Vendor acknowledgement",
            count=len(po_waiting(PoStatus.ISSUED)),
            oldest_days=oldest([p.issued_at for p in po_waiting(PoStatus.ISSUED)]),
        ),
    ]
    months = [
        MonthPoint(month=m, pos_issued=len(v), median_cycle_days=round(median(v), 1))
        for m, v in sorted(by_month.items())[-12:]
    ]
    return Measures(
        cycle=_duration("Request raised to PO issued", cycle),
        stages=[
            _duration("Raised to submitted", s_sub),
            _duration("Submitted to approved", s_appr),
            _duration("Approved to vendor chosen", s_choose),
            _duration("Vendor chosen to PO issued", s_po),
        ],
        submitted=len(submitted),
        reworked=len(reworked),
        rework_rate=round(len(reworked) / len(submitted), 3) if submitted else None,
        rejected=len(by_status[RequestStatus.REJECTED]),
        waiting=waiting,
        months=months,
    )
