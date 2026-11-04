"""The management pack PDF: made only from content the Controller and the CFO both signed
off, stored once (bytes, their SHA-256, the source and content hashes, the reviewers) and
checked byte for byte whenever it is read back. An edit to the case afterwards leaves the
pack as history; a new one needs fresh sign-offs."""

import hashlib
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseNotFoundError
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.cases.schemas import CaseDetail
from src.app.service_pod.core.cases.service import current_fingerprint, get_case
from src.app.service_pod.core.messaging.models import ArtifactKind, ArtifactStatus, PodArtifact
from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey
from src.app.service_pod.flows.fpa_trend.service import month_name
from src.app.service_pod.flows.reporting.models import PodReportPack
from src.app.service_pod.flows.reporting.pdf import Pack
from src.app.service_pod.flows.reporting.schemas import PackOut


class PackIntegrityError(AppError):
    status_code = 409
    code = "pack_integrity"


async def _reporting_case(session: AsyncSession, case_id: uuid.UUID, lock: bool = False) -> PodCase:
    case = await load_case(session, case_id, lock=lock)
    if case.workflow != WorkflowKey.REPORTING:
        raise CaseNotFoundError
    return case


def _money(value: Any, currency: str) -> str:
    return f"{currency} {Decimal(str(value)):,.0f}"


def _pct(value: Any) -> str:
    return "undefined" if value is None else f"{Decimal(str(value)):+.1f}%"


def build_pdf(case: PodCase, detail: CaseDetail, reviewers: list[dict[str, Any]]) -> bytes:
    s = case.state
    cur = str(s.get("currency", ""))
    month, prior = str(s["report_month"]), str(s["prior_month"])
    pack = Pack(f"{case.reference} management pack {month_name(month)}")
    pack.heading(f"Management pack - {month_name(month)}", 16)
    pack.paragraph(
        f"{case.reference} · {detail.snapshot.company_name} · entity {detail.entity.code} · "
        f"{s.get('basis')} basis · {cur}"
        + (f" · {s['business_unit']}" if s.get("business_unit") else "")
    )
    pack.paragraph(
        f"Source as of {detail.snapshot.as_of}, SHA-256 {detail.snapshot.sha256}", size=9
    )
    pack.rule()

    metrics = {m["period"]: m for m in s["metrics"]}
    p, c = metrics[prior], metrics[month]
    change = s["changes"][-1]
    pack.heading("Profit and loss")
    rows = [("", month_name(prior), month_name(month), "Change", "Change %")]
    for key, label, move in (
        ("revenue", "Revenue", "revenue"),
        ("cost_of_services", "Cost of services", "cost_of_services"),
        ("operating_expense", "Operating expenses", "operating_expense"),
        ("operating_profit", "Operating profit", "operating_profit"),
    ):
        rows.append(
            (
                label,
                _money(p[key], cur),
                _money(c[key], cur),
                _money(change[move]["change"], cur),
                _pct(change[move]["pct"]),
            )
        )
    rows.append(
        (
            "Operating margin",
            "undefined" if p["margin_pct"] is None else f"{Decimal(p['margin_pct']):.1f}%",
            "undefined" if c["margin_pct"] is None else f"{Decimal(c['margin_pct']):.1f}%",
            "undefined"
            if change["margin_pp_exact"] is None
            else f"{Decimal(change['margin_pp_exact']):+.2f} pp",
            "",
        )
    )
    pack.table(rows, [140, 95, 95, 90, 79])

    pack.heading("Balance sheet")
    sheet_rows: list[tuple[str, ...]] = [("", month_name(prior), month_name(month))]
    sheets = s.get("balance_sheets") or {}
    for key in ("assets", "liabilities", "equity"):
        sheet_rows.append(
            (
                f"Total {key}",
                *(
                    _money(sheets[m][key], cur) if sheets.get(m) else "missing"
                    for m in (prior, month)
                ),
            )
        )
    pack.table(sheet_rows, [180, 160, 160])

    aging = s["aging"]
    pack.heading("Accounts receivable aging")
    pack.paragraph(
        f"Open balances as of {aging['as_of']}"
        + ("" if aging["matches_month_end"] else f" (not the month end {aging['month_end']})"),
        size=9,
    )
    pack.table(
        [("Bucket", "Invoices", "Open")]
        + [(b["label"], str(b["count"]), _money(b["amount"], cur)) for b in aging["buckets"]]
        + [("Total", "", _money(aging["total"], cur))],
        [180, 120, 200],
    )

    pack.heading("Control checks")
    for ctl in s.get("controls", []):
        pack.paragraph(
            f"[{'x' if ctl['status'] == 'pass' else ' '}] {ctl['label']}: {ctl['detail']}", 9
        )

    commentary = s.get("commentary") or {}
    pack.heading("Commentary")
    known = {f["id"]: f for f in commentary.get("facts", [])}
    for h in commentary.get("highlights", []):
        pack.paragraph(f"- {h['text']}")
        cited = [known[i] for i in h.get("fact_ids", []) if i in known]
        if cited:
            pack.paragraph("   " + "; ".join(f"{f['label']}: {f['value']}" for f in cited), size=9)
    if s.get("follow_ups"):
        pack.heading("Open questions and follow-ups", 10)
        for f in s["follow_ups"]:
            pack.paragraph(f"- {f['text']}", size=9)
    limitations = [t for t in detail.review_tasks if t.kind == "scope" and t.status == "resolved"]
    if s.get("caveats") or limitations:
        pack.heading("Caveats and disclosed limitations", 10)
        for cv in s.get("caveats", []):
            pack.paragraph(f"- {cv}", size=9)
        for t in limitations:
            pack.paragraph(f"- {t.detail} Resolution: {t.resolution}", size=9)

    pack.rule()
    pack.heading("Sign-offs")
    for r in reviewers:
        pack.paragraph(f"Signed off as {r['capacity']} by {r['name']} on {r['at']}", size=9)
    pack.paragraph(f"Content fingerprint {detail.fingerprint}", size=9)
    pack.paragraph(
        "Application approvals bound to this content; not a cryptographic certificate signature.",
        size=9,
    )
    return pack.render()


async def _out(session: AsyncSession, case: PodCase, packs: list[PodReportPack]) -> list[PackOut]:
    fingerprint = await current_fingerprint(session, case)
    return [
        PackOut(
            id=p.id,
            number=p.number,
            sha256=p.sha256,
            size=p.size,
            content_hash=p.content_hash,
            source_sha=p.source_sha,
            reviewers=p.reviewers,
            artifact_id=p.artifact_id,
            current=p.content_hash == fingerprint,
            created_at=p.created_at,
        )
        for p in packs
    ]


async def list_packs(session: AsyncSession, case_id: uuid.UUID) -> list[PackOut]:
    case = await _reporting_case(session, case_id)
    packs = await session.scalars(
        select(PodReportPack).where(PodReportPack.case_id == case.id).order_by(PodReportPack.number)
    )
    return await _out(session, case, list(packs))


async def export_pack(
    session: AsyncSession, access: PodAccess, case_id: uuid.UUID, ctx: RequestContext
) -> PackOut:
    """Make (once per signed-off content) the PDF pack and store it immutably."""
    case = await _reporting_case(session, case_id, lock=True)
    detail = await get_case(session, access, case.id)
    needed = WORKFLOWS[case.workflow].signoffs
    valid = {a.capacity: a for a in detail.approvals if a.valid}
    if case.status not in (CaseStatus.APPROVED, CaseStatus.COMPLETED) or not all(
        n in valid for n in needed
    ):
        raise CaseActionError(
            "The pack is exported once the Controller and the CFO have signed off."
        )
    existing = await session.scalar(
        select(PodReportPack).where(
            PodReportPack.case_id == case.id, PodReportPack.content_hash == detail.fingerprint
        )
    )
    if existing is not None:
        return (await _out(session, case, [existing]))[0]
    reviewers = [
        {
            "capacity": n,
            "name": valid[n].user.name,
            "at": valid[n].created_at.strftime("%Y-%m-%d %H:%M UTC"),
        }
        for n in needed
    ]
    data = build_pdf(case, detail, reviewers)
    digest = hashlib.sha256(data).hexdigest()
    number = (
        await session.scalar(
            select(func.coalesce(func.max(PodReportPack.number), 0)).where(
                PodReportPack.case_id == case.id
            )
        )
        or 0
    ) + 1
    filename = f"{case.reference}-management-pack-v{number}.pdf"
    artifact = PodArtifact(
        case_id=case.id,
        kind=ArtifactKind.SUPPORTING,
        invoice_refs=[],
        filename=filename,
        content_type="application/pdf",
        size=len(data),
        sha256=digest,
        content=data,
        status=ArtifactStatus.APPROVED,
        uploaded_by=access.user.id,
        decided_by=access.user.id,
        decided_at=utcnow(),
    )
    session.add(artifact)
    await session.flush()
    pack = PodReportPack(
        case_id=case.id,
        number=number,
        content_hash=detail.fingerprint,
        source_sha=case.snapshot_sha,
        sha256=digest,
        size=len(data),
        reviewers=reviewers,
        pdf=data,
        artifact_id=artifact.id,
        created_by=access.user.id,
    )
    session.add(pack)
    record_event(
        session,
        "pod.report_pack_exported",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        case_id=str(case.id),
        sha256=digest,
        content_hash=detail.fingerprint,
        summary=f"{case.reference}: exported management pack v{number} ({filename})",
    )
    await session.flush()
    out = (await _out(session, case, [pack]))[0]
    await session.commit()
    return out


async def read_pack(
    session: AsyncSession, case_id: uuid.UUID, pack_id: uuid.UUID
) -> tuple[str, bytes]:
    """The stored bytes, after checking they still hash to what was recorded."""
    case = await _reporting_case(session, case_id)
    pack = await session.scalar(
        select(PodReportPack)
        .options(undefer(PodReportPack.pdf))
        .where(PodReportPack.id == pack_id, PodReportPack.case_id == case.id)
    )
    if pack is None:
        raise CaseNotFoundError("Pack not found.")
    if hashlib.sha256(pack.pdf).hexdigest() != pack.sha256:
        raise PackIntegrityError("The stored pack doesn't match its recorded hash: don't use it.")
    return f"{case.reference}-management-pack-v{pack.number}.pdf", pack.pdf
