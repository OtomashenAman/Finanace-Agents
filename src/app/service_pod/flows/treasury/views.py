"""Treasury screens beyond the case: the sources a forecast can start from, and the export."""

import csv
import io
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.exceptions import CaseNotFoundError, CaseSelectionError
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    CommitmentStatus,
    PodCase,
    PodCommitment,
)
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.treasury import engine
from src.app.service_pod.flows.treasury.schemas import CashSource, TreasuryCaseRow, TreasurySources

NEEDED = {"cash_position", "invoices", "planned_outflows"}


async def sources(session: AsyncSession) -> TreasurySources:
    out = []
    for summary in await snapshots.list_snapshots(session, None):
        if not set(summary.coverage) >= NEEDED:
            continue
        snap = await session.get(PodSnapshot, summary.id)
        assert snap is not None  # noqa: S101
        doc = snapshots.document(snap)
        checks: list[str] = []
        try:
            cash, issues = engine.opening_cash(doc)
            checks = [i["detail"] for i in issues]
        except CaseSelectionError as exc:
            cash, checks = None, [exc.message]
        commitments = await session.scalar(
            select(func.count())
            .select_from(PodCommitment)
            .join(PodCase, PodCase.id == PodCommitment.case_id)
            .where(
                PodCase.entity_id == snap.entity_id,
                PodCase.workflow == WorkflowKey.AR_COLLECTIONS,
                PodCase.status != CaseStatus.CANCELLED,
                PodCommitment.status == CommitmentStatus.APPROVED,
            )
        )
        out.append(
            CashSource(
                snapshot=summary,
                opening_cash=cash["bank_balance"] if cash else None,
                policy_buffer=cash["policy_buffer"] if cash else None,
                checks=checks,
                approved_outflows=sum(
                    (o.amount for o in doc.planned_outflows or [] if o.approved),
                    start=engine.ZERO,
                ),
                commitments=commitments or 0,
            )
        )
    cases = await session.scalars(
        select(PodCase)
        .where(PodCase.workflow == WorkflowKey.TREASURY)
        .order_by(PodCase.created_at.desc())
        .limit(50)
    )
    return TreasurySources(
        sources=out,
        cases=[
            TreasuryCaseRow(
                id=str(c.id),
                reference=c.reference,
                title=c.title,
                status=c.status.value,
                as_of=str(c.state.get("as_of", "")),
            )
            for c in cases
        ],
    )


async def forecast_csv(session: AsyncSession, case_id: uuid.UUID) -> tuple[str, str]:
    """The 91 days of every scenario (filename, CSV text)."""
    case = await load_case(session, case_id)
    if case.workflow != WorkflowKey.TREASURY:
        raise CaseNotFoundError
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["scenario", "date", "inflow", "outflow", "cash", "headroom", "shortfall"])
    for name, result in (case.state.get("results") or {}).items():
        for d in result["days"]:
            writer.writerow(
                [
                    name,
                    d["date"],
                    d["inflow"],
                    d["outflow"],
                    d["cash"],
                    d["headroom"],
                    d["shortfall"],
                ]
            )
    return f"{case.reference}-cash-forecast.csv", out.getvalue()
