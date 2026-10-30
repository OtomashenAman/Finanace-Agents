"""The AR portfolio: open AR, aging and priority customers of one snapshot plus the cases
already open on it. Every figure comes from the source rows; nothing is estimated."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.common.worklists import (
    CaseRef,
    InvoiceRow,
    latest_snapshot,
    open_cases,
    require_workflow_role,
)
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import (
    CommitmentStatus,
    PodCase,
    PodCommitment,
    PodReviewTask,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from src.app.service_pod.core.messaging.models import Direction, MessageStatus, PodMessage
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import Collection, SnapshotDocument
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.ar_collections.promises import missed, promise_rows
from src.app.service_pod.flows.ar_collections.schemas import (
    AgingBucket,
    ArPortfolio,
    PortfolioCustomer,
)

PRIORITY_DAYS = 30  # the deck's "overdue > 30 days" measure (a priority, not an eligibility)


BUCKETS = (
    ("Current", None, 0),
    ("1-30", 1, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


def _overdue(doc: SnapshotDocument, customer_id: str) -> list[InvoiceRow]:
    return [
        InvoiceRow(
            id=i.id,
            number=i.number,
            due_date=i.due_date,
            balance=i.balance,
            days_overdue=(doc.as_of - i.due_date).days,
        )
        for i in doc.invoices or []
        if i.customer_id == customer_id and i.balance > 0 and i.due_date < doc.as_of
    ]


async def _next_action(
    session: AsyncSession, case: PodCase | None, max_days: int, missed_promise: bool = False
) -> str:
    if case is None:
        return (
            "Request a payment schedule" if max_days > PRIORITY_DAYS else "Send an overdue reminder"
        )
    if missed_promise:
        return "Follow up on the missed promise"
    kinds = set(
        await session.scalars(
            select(PodReviewTask.kind).where(
                PodReviewTask.case_id == case.id, PodReviewTask.status == ReviewTaskStatus.OPEN
            )
        )
    )
    if ReviewTaskKind.MISSING_DOCUMENT in kinds:
        return "Send the requested documents"
    if ReviewTaskKind.DISPUTE in kinds:
        return "Resolve the dispute"
    if ReviewTaskKind.UNKNOWN_DATE in kinds:
        return "Ask for the missing payment date"
    proposed = await session.scalar(
        select(func.count())
        .select_from(PodCommitment)
        .where(PodCommitment.case_id == case.id, PodCommitment.status == CommitmentStatus.PROPOSED)
    )
    if proposed:
        return "Review the proposed commitments"
    statuses = set(
        await session.scalars(
            select(PodMessage.status).where(
                PodMessage.case_id == case.id, PodMessage.direction == Direction.OUTBOUND
            )
        )
    )
    if MessageStatus.SENT in statuses:
        return "Wait for the reply / follow up"
    if statuses & {MessageStatus.DRAFT, MessageStatus.APPROVED}:
        return "Approve and send the draft"
    return "Draft the payment schedule request"


async def ar_portfolio(
    session: AsyncSession, access: PodAccess, snapshot_id: uuid.UUID | None
) -> ArPortfolio:
    require_workflow_role(access, WorkflowKey.AR_COLLECTIONS)
    snap = await latest_snapshot(
        session, access, snapshot_id, {Collection.CUSTOMERS, Collection.INVOICES}
    )
    empty = [AgingBucket(label=b[0], amount=Decimal(0), count=0) for b in BUCKETS]
    if snap is None:
        return ArPortfolio(
            snapshot=None,
            currency=None,
            ar_balance=Decimal(0),
            overdue_over_30=Decimal(0),
            approved_promises=Decimal(0),
            open_exceptions=0,
            aging=empty,
            customers=[],
            promises=[],
        )
    doc = snapshots.document(snap)
    open_items = [i for i in doc.invoices or [] if i.balance > 0]
    aging = []
    for label, low, high in BUCKETS:
        rows = [
            i
            for i in open_items
            if (low is None and i.due_date >= doc.as_of)
            or (
                low is not None
                and (doc.as_of - i.due_date).days >= low
                and (high is None or (doc.as_of - i.due_date).days <= high)
            )
        ]
        aging.append(
            AgingBucket(
                label=label, amount=sum((i.balance for i in rows), Decimal(0)), count=len(rows)
            )
        )

    cases = await open_cases(session, access, WorkflowKey.AR_COLLECTIONS, snap.entity_id)
    case_ids = [c.id for c in cases]
    by_customer = {str(c.selection.get("customer_id")): c for c in cases}
    promises = (
        await session.scalar(
            select(func.coalesce(func.sum(PodCommitment.amount), 0)).where(
                PodCommitment.case_id.in_(case_ids),
                PodCommitment.status == CommitmentStatus.APPROVED,
            )
        )
        if case_ids
        else 0
    )
    exceptions = (
        await session.scalar(
            select(func.count())
            .select_from(PodReviewTask)
            .where(
                PodReviewTask.case_id.in_(case_ids), PodReviewTask.status == ReviewTaskStatus.OPEN
            )
        )
        if case_ids
        else 0
    )

    watched = await promise_rows(session, cases, doc)
    late = missed(watched)
    customers = []
    for customer in doc.customers or []:
        overdue = _overdue(doc, customer.id)
        if not overdue:
            continue
        case = by_customer.get(customer.id)
        max_days = max(r.days_overdue for r in overdue)
        customers.append(
            PortfolioCustomer(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
                overdue=sum((r.balance for r in overdue), Decimal(0)),
                max_days_overdue=max_days,
                invoices=overdue,
                open_case=CaseRef(id=case.id, reference=case.reference, status=case.status)
                if case
                else None,
                next_action=await _next_action(
                    session, case, max_days, case is not None and case.id in late
                ),
            )
        )
    customers.sort(key=lambda c: (c.max_days_overdue > PRIORITY_DAYS, c.overdue), reverse=True)
    return ArPortfolio(
        snapshot=await snapshots.summary(session, snap),
        currency=doc.currency,
        ar_balance=sum((i.balance for i in open_items), Decimal(0)),
        overdue_over_30=sum(
            (i.balance for i in open_items if (doc.as_of - i.due_date).days > PRIORITY_DAYS),
            Decimal(0),
        ),
        approved_promises=Decimal(promises or 0),
        open_exceptions=int(exceptions or 0),
        aging=aging,
        customers=customers,
        promises=watched,
    )
