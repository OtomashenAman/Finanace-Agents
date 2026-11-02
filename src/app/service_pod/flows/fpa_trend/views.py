"""FP&A screens beyond the case: the periods a source can analyse, a drill into one
account's transactions, the evidence export and the approved pack."""

import csv
import io
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseNotFoundError
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.cases.service import get_case
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.fpa_trend import engine
from src.app.service_pod.flows.fpa_trend.schemas import FpaCaseRow, FpaPeriods, PeriodSource


async def periods(session: AsyncSession) -> FpaPeriods:
    sources = []
    for summary in await snapshots.list_snapshots(session, None):
        if not {"accounts", "gl_lines", "transactions"} <= set(summary.coverage):
            continue
        snap = await session.get(PodSnapshot, summary.id)
        assert snap is not None  # noqa: S101
        doc = snapshots.document(snap)
        months = engine.available_months(doc)
        suggested = engine.suggested_range(months)
        sources.append(
            PeriodSource(
                snapshot=summary,
                months=months,
                business_units=sorted(
                    {g.business_unit for g in doc.gl_lines or [] if g.business_unit}
                ),
                suggested_start=suggested[0] if suggested else None,
                suggested_end=suggested[1] if suggested else None,
            )
        )
    cases = await session.scalars(
        select(PodCase)
        .where(PodCase.workflow == WorkflowKey.FPA_TREND)
        .order_by(PodCase.created_at.desc())
        .limit(50)
    )
    return FpaPeriods(
        sources=sources,
        cases=[
            FpaCaseRow(
                id=str(c.id),
                reference=c.reference,
                title=c.title,
                status=c.status.value,
                start=str(c.selection.get("start", "")),
                end=str(c.selection.get("end", "")),
            )
            for c in cases
        ],
    )


async def _fpa_case(session: AsyncSession, case_id: uuid.UUID) -> PodCase:
    case = await load_case(session, case_id)
    if case.workflow != WorkflowKey.FPA_TREND:
        raise CaseNotFoundError
    return case


async def drill(
    session: AsyncSession, case_id: uuid.UUID, account_id: str, period: str
) -> dict[str, Any]:
    """One account in one month: its GL line(s) and every transaction (any status)."""
    case = await _fpa_case(session, case_id)
    snap = await session.get(PodSnapshot, case.snapshot_id)
    assert snap is not None  # noqa: S101
    doc = snapshots.document(snap)
    account = next((a for a in doc.accounts or [] if a.id == account_id), None)
    if account is None:
        raise CaseNotFoundError("That account isn't in the case's source.")
    data: dict[str, Any] = plain(
        {
            "account": account,
            "period": period,
            "gl_lines": [
                g for g in doc.gl_lines or [] if (g.account_id, g.period) == (account_id, period)
            ],
            "transactions": sorted(
                (
                    t
                    for t in doc.transactions or []
                    if (t.account_id, t.period) == (account_id, period)
                ),
                key=lambda t: (t.date, t.id),
            ),
        }
    )
    return data


EVIDENCE_COLUMNS = [
    "from",
    "to",
    "section",
    "account",
    "counterparty",
    "contributor_change",
    "transaction_id",
    "type",
    "date",
    "period",
    "amount",
    "document_ref",
    "gl_line_id",
]


async def evidence_csv(session: AsyncSession, case_id: uuid.UUID) -> tuple[str, str]:
    """Every contributor and the transactions behind it (filename, CSV text)."""
    case = await _fpa_case(session, case_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EVIDENCE_COLUMNS)
    for change in case.state.get("changes", []):
        groups: list[tuple[str, str, dict[str, Any]]] = [
            ("revenue", "revenue", d) for d in change.get("revenue_drivers", [])
        ]
        for acct in change.get("cost_drivers", []):
            groups += [("cost", acct["account"], d) for d in acct["contributors"]]
        for section, account, d in groups:
            for t in d["transactions"]:
                writer.writerow(
                    [
                        change["from"],
                        change["to"],
                        section,
                        account,
                        d["counterparty"],
                        d["change"],
                        t["id"],
                        t["type"],
                        t["date"],
                        t["period"],
                        t["amount"],
                        t["document_ref"] or "",
                        t["gl_line_id"] or "",
                    ]
                )
    return f"{case.reference}-evidence.csv", out.getvalue()


async def approved_pack(
    session: AsyncSession, access: PodAccess, case_id: uuid.UUID
) -> tuple[str, dict[str, Any]]:
    """The pack exactly as signed off (TDD: the Finance Head exports the current approved
    pack). Refused while no valid sign-off covers the current content."""
    case = await _fpa_case(session, case_id)
    detail = await get_case(session, access, case.id)
    valid = [a for a in detail.approvals if a.valid]
    if case.status not in (CaseStatus.APPROVED, CaseStatus.COMPLETED) or not valid:
        raise CaseActionError("The pack can be exported once the Finance Head has signed it off.")
    approval = valid[-1]
    state = case.state
    pack = {
        "case": case.reference,
        "title": case.title,
        "status": case.status.value,
        "source": {
            "company": detail.snapshot.company_name,
            "as_of": detail.snapshot.as_of,
            "sha256": detail.snapshot.sha256,
            "basis": state.get("basis"),
            "currency": state.get("currency"),
        },
        "selection": case.selection,
        "metrics": state.get("metrics"),
        "changes": [
            {k: v for k, v in c.items() if k not in ("revenue_drivers", "cost_drivers")}
            | {
                "revenue_drivers": [
                    {"counterparty": d["counterparty"], "change": d["change"]}
                    for d in c.get("revenue_drivers", [])
                ],
                "cost_drivers": [
                    {"account": d["account"], "change": d["change"]}
                    for d in c.get("cost_drivers", [])
                ],
            }
            for c in state.get("changes", [])
        ],
        "yoy": state.get("yoy"),
        "caveats": state.get("caveats"),
        "commentary": state.get("commentary"),
        "recommended_actions": state.get("recommended_actions"),
        "open_questions": [
            {"detail": t.detail, "status": t.status, "resolution": t.resolution}
            for t in detail.review_tasks
        ],
        "follow_up_actions": [
            {"title": a.title, "owner": a.owner.name, "status": a.status}
            for a in detail.owned_actions
        ],
        "corrections": state.get("corrections", []),
        "signed_off": {
            "as": approval.capacity,
            "by": approval.user.name,
            "at": approval.created_at,
            "content_fingerprint": approval.content_hash,
        },
    }
    return f"{case.reference}-pack.json", plain(pack)
