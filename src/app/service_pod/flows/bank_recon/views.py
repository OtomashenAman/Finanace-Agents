"""Unapplied cash: bank receipts not yet recorded in QuickBooks, with the matched payer and
the cases already open on them."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.common.matching import customer_key
from src.app.service_pod.common.worklists import (
    InvoiceRow,
    case_ref,
    latest_snapshot,
    open_cases,
)
from src.app.service_pod.core.cases.models import (
    PodCase,
)
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.snapshots.exceptions import SnapshotNotFoundError
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskStatus
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.bank_recon.schemas import BankWorklist, ReceiptRow


async def bank_worklist(session: AsyncSession, snapshot_id: uuid.UUID | None) -> BankWorklist:
    snap = await latest_snapshot(session, snapshot_id, {Collection.BANK_RECEIPTS})
    if snap is None:
        return BankWorklist(
            snapshot=None,
            unmatched_total=Decimal(0),
            receipts=0,
            possible_duplicates=0,
            pending_admin=0,
            rows=[],
        )
    doc = snapshots.document(snap)
    if snapshot_id is not None and not doc.bank_receipts:
        raise SnapshotNotFoundError("That snapshot has no bank receipts.")
    recorded = {p.reference.lower() for p in doc.payments or []}
    customers = {customer_key(c.name): c for c in doc.customers or []}
    cases = await open_cases(session, WorkflowKey.BANK_RECON, snap.entity_id)
    by_receipt = {str(c.selection.get("receipt_reference", "")).lower(): c for c in cases}

    rows = []
    for r in doc.bank_receipts or []:
        if r.reference.lower() in recorded:
            continue
        customer = customers.get(customer_key(r.payer))
        duplicate = any(
            p.amount == r.amount
            and customer is not None
            and p.customer_id == customer.id
            and abs((p.date - r.date).days) <= 3
            for p in doc.payments or []
        )
        case = by_receipt.get(r.reference.lower())
        rows.append(
            ReceiptRow(
                reference=r.reference,
                payer=r.payer,
                date=r.date,
                amount=r.amount,
                currency=r.currency,
                cleared=r.cleared,
                matched_customer_id=customer.id if customer else None,
                matched_customer=customer.name if customer else None,
                open_invoices=[
                    InvoiceRow(
                        id=i.id,
                        number=i.number,
                        due_date=i.due_date,
                        balance=i.balance,
                        days_overdue=max(0, (doc.as_of - i.due_date).days),
                    )
                    for i in doc.invoices or []
                    if customer and i.customer_id == customer.id and i.balance > 0
                ],
                possible_duplicate=duplicate,
                open_case=case_ref(case),
            )
        )
    pending = await session.scalar(
        select(func.count())
        .select_from(PodPostingTask)
        .join(PodCase, PodCase.id == PodPostingTask.case_id)
        .where(
            PodCase.entity_id == snap.entity_id,
            PodCase.workflow == WorkflowKey.BANK_RECON,
            PodPostingTask.status.in_([TaskStatus.PROPOSED, TaskStatus.RECORDED_UNVERIFIED]),
        )
    )
    return BankWorklist(
        snapshot=await snapshots.summary(session, snap),
        unmatched_total=sum((r.amount for r in rows if r.cleared), Decimal(0)),
        receipts=len(rows),
        possible_duplicates=sum(r.possible_duplicate for r in rows),
        pending_admin=int(pending or 0),
        rows=rows,
    )
