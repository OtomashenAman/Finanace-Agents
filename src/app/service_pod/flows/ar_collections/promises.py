"""Watching approved promises after the schedule is approved (TDD section 6: "monitor
follow-up actions"). A promise counts as kept only on evidence of cash: a verified bank
posting applied to the invoice, or a newer source showing the invoice's balance went down.
Never on the promise itself."""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common import clock
from src.app.service_pod.common.reading import dec
from src.app.service_pod.core.cases.models import (
    CommitmentStatus,
    PodCase,
    PodCommitment,
)
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskStatus
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.ar_collections.schemas import PromiseRow

DUE_SOON_DAYS = 2  # "response due tomorrow" (deck slide 32): flag a little ahead


async def verified_receipts(
    session: AsyncSession, entity_id: uuid.UUID
) -> dict[str, list[tuple[Decimal, str]]]:
    """invoice id -> [(amount, bank reference)] of bank postings verified in QuickBooks."""
    rows = await session.execute(
        select(PodCase)
        .join(PodPostingTask, PodPostingTask.case_id == PodCase.id)
        .where(
            PodCase.entity_id == entity_id,
            PodCase.workflow == WorkflowKey.BANK_RECON,
            PodPostingTask.status == TaskStatus.VERIFIED,
        )
    )
    found: dict[str, list[tuple[Decimal, str]]] = defaultdict(list)
    for (case,) in rows:
        reference = str(case.state.get("receipt", {}).get("reference", case.reference))
        for line in (case.state.get("allocation") or {}).get("lines", []):
            found[str(line["invoice_id"])].append((dec(line["amount"]), reference))
    return found


async def promise_rows(
    session: AsyncSession, cases: list[PodCase], latest: SnapshotDocument
) -> list[PromiseRow]:
    """Approved promises of these AR cases, oldest date first, with whether cash came in."""
    if not cases:
        return []
    by_id = {c.id: c for c in cases}
    commitments = list(
        await session.scalars(
            select(PodCommitment)
            .where(
                PodCommitment.case_id.in_(list(by_id)),
                PodCommitment.status == CommitmentStatus.APPROVED,
                PodCommitment.expected_date.is_not(None),
            )
            .order_by(PodCommitment.expected_date, PodCommitment.created_at)
        )
    )
    bank = await verified_receipts(session, cases[0].entity_id)
    balances = {i.id: i.balance for i in latest.invoices or []}
    today = clock.utcnow().date()

    # Cash per (case, invoice): the larger of the two pieces of evidence, never their sum
    cash: dict[tuple[uuid.UUID, str], tuple[Decimal, str | None]] = {}
    for case in cases:
        for inv in case.state.get("invoices", []):
            invoice_id = str(inv["id"])
            dropped = dec(inv["balance"]) - balances.get(invoice_id, dec(inv["balance"]))
            posted = bank.get(invoice_id, [])
            posted_total = sum((a for a, _ in posted), Decimal(0))
            if posted_total >= dropped and posted_total > 0:
                label = ", ".join(sorted({ref for _, ref in posted})) + " (verified)"
                cash[(case.id, invoice_id)] = (posted_total, label)
            elif dropped > 0:
                cash[(case.id, invoice_id)] = (dropped, "a newer source")

    rows = []
    used: dict[tuple[uuid.UUID, str], Decimal] = defaultdict(Decimal)
    for x in commitments:
        case = by_id[x.case_id]
        key = (case.id, x.invoice_id)
        available, evidence = cash.get(key, (Decimal(0), None))
        # Promises on an invoice are met in date order (first promised, first paid)
        received = available - used[key] >= x.amount
        if received:
            used[key] += x.amount
        expected = x.expected_date
        assert expected is not None  # noqa: S101 - filtered in the query
        days = (expected - today).days
        state = (
            "received"
            if received
            else "overdue"
            if days < 0
            else "due"
            if days <= DUE_SOON_DAYS
            else "upcoming"
        )
        rows.append(
            PromiseRow(
                case_id=case.id,
                case_reference=case.reference,
                customer=str(case.state.get("customer", {}).get("name", case.title)),
                invoice_number=x.invoice_number,
                amount=x.amount,
                expected_date=expected,
                days_until=days,
                state=state,
                received_by=evidence if received else None,
            )
        )
    order = {"overdue": 0, "due": 1, "upcoming": 2, "received": 3}
    return sorted(rows, key=lambda r: (order[r.state], r.expected_date))


def missed(rows: list[PromiseRow]) -> set[uuid.UUID]:
    return {r.case_id for r in rows if r.state == "overdue"}
