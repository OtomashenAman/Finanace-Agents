"""The close's own rules: one case per entity and month, the evidence pack and the accrual
journals proposed on sign-off (the controller posts them), the requirement's rules, the
measures and the daily reconciliation and deadline check."""

from __future__ import annotations

import hashlib
import io
import json
import re
import statistics
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.common.clock import utcnow
from src.app.finance_pod.common import doc_of, jsonable, policy_values, result
from src.app.finance_pod.flows.ap_month_close import agents
from src.app.finance_pod.flows.ap_month_close.policy import ApcPolicy
from src.app.finance_pod.flows.ap_month_close.results import (
    Explanation,
    Review,
    StatementCheck,
)
from src.app.jobs import queue as jobs
from src.app.jobs.queue import JobContext
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from src.app.service_pod.core.messaging.models import ArtifactChannel, ArtifactKind, PodArtifact
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.snapshots.models import PodSnapshot, PodSnapshotArchive
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.spec import StepFailedError, StepStatus
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

KEY = WorkflowKey.AP_MONTH_CLOSE
DAILY_JOB = "finance.apc_daily"
PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
EVIDENCE_NAME = "evidence-{reference}-{period}.zip"


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    period = str(case.selection.get("period") or "")
    if not PERIOD.match(period):
        raise CaseSelectionError("Choose the month to close (YYYY-MM).")
    end = agents.period_end(period)
    if doc.as_of < end:
        raise CaseSelectionError(
            f"This snapshot is as of {doc.as_of}: take one after {end}, the end of {period}."
        )
    if refresh:
        return
    taken = await session.scalar(
        select(PodCase).where(
            PodCase.workflow == KEY,
            PodCase.entity_id == case.entity_id,
            PodCase.selection["period"].astext == period,
            PodCase.status != CaseStatus.CANCELLED,
        )
    )
    if taken is not None:
        raise CaseSelectionError(f"{period} is already being closed in {taken.reference}.")
    version, values = await policy_values(session, KEY.value, ApcPolicy)
    case.state = {
        **case.state,
        "policy": {"version": version, "values": values.model_dump(mode="json")},
    }


def deadline(period: str, close_day: int) -> date:
    """The day of the next month by which the month's accruals are posted (AP6.R1)."""
    return agents.period_end(period) + timedelta(days=close_day)


# --- rules ---------------------------------------------------------------------------------


async def explained_rule(c: Ctx) -> str | None:
    """AP6.R2 Reconciliation signed every month: a difference no posting explains is signed
    only with the reviewer's word on it."""
    explanation = result(c, "6.1.2.b", Explanation)
    if explanation is None or explanation.unexplained == 0:
        return None
    review = result(c, "6.2.1.a", Review)
    if review is not None and review.comment:
        return None
    return (
        f"{explanation.unexplained} of the reconciliation is unexplained: the controller's "
        "review must say why before sign-off (AP6.R2)."
    )


# --- on sign-off: evidence pack and the accrual journals ---------------------------------------


async def evidence_pack(c: Ctx) -> bytes:
    """Every step result, the review and sign-off, the case's audit trail, and a manifest of
    the files' SHA-256 (AP6.R3, AP6.P3)."""
    events = list(
        await c.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.details["run"].astext == c.case.reference)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )
    snapshot = await c.session.get(PodSnapshot, c.case.snapshot_id)
    files: dict[str, Any] = {
        "case.json": {
            "reference": c.case.reference, "title": c.case.title,
            "period": c.case.selection["period"], "snapshot_id": str(c.case.snapshot_id),
            "snapshot_sha256": c.case.snapshot_sha,
            "source": snapshot.source_reference if snapshot else None,
            "policy": c.case.state.get("policy"), "content_fingerprint": c.fingerprint,
        },
        "steps.json": [
            {"l5": r.l5_code, "status": r.status.value, "result": r.result, "note": r.note,
             "done_by": str(r.done_by) if r.done_by else None,
             "done_at": r.done_at.isoformat() if r.done_at else None}
            for r in c.children.steps
        ],
        "review_tasks.json": [
            {"subject": t.subject, "detail": t.detail, "status": t.status.value,
             "resolution": t.resolution}
            for t in c.children.review_tasks
        ],
        "audit.json": [
            {"seq": e.seq, "hash": e.hash, "type": e.event_type,
             "actor_id": str(e.actor_id) if e.actor_id else None,
             "at": e.created_at.isoformat(), "details": e.details}
            for e in events
        ],
    }  # fmt: skip
    blobs = {
        name: json.dumps(jsonable(body), indent=2, sort_keys=True, default=str).encode()
        for name, body in files.items()
    }
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in blobs.items()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
        for name, data in blobs.items():
            pack.writestr(name, data)
        pack.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return buffer.getvalue()


async def on_sign_off(c: Ctx) -> None:
    """6.2.2.a Approve; evidence auto-filed. The agent proposes the accrual and its reversal;
    the controller posts them (AP6.G1), and a fresh snapshot verifies them before the close
    completes."""
    data = await evidence_pack(c)
    period = c.case.selection["period"]
    c.session.add(
        PodArtifact(
            case_id=c.case.id, kind=ArtifactKind.EVIDENCE, invoice_refs=[],
            filename=EVIDENCE_NAME.format(reference=c.case.reference, period=period),
            content_type="application/zip", size=len(data),
            sha256=hashlib.sha256(data).hexdigest(), content=data, uploaded_by=None,
            channel=ArtifactChannel.UPLOAD,
        )
    )  # fmt: skip
    doc = await doc_of(c)
    for reverse in (False, True):
        journal = agents.accrual_journal(c, doc, reverse)
        if journal is None:
            continue
        await tasks.add_task(
            c.session, c.case,
            TaskCreate(kind=TaskKind.CREATE_JOURNAL_ENTRY,
                       reference=f"{c.case.reference} {'reversal' if reverse else 'accrual'}",
                       instructions={"doc": journal}),
            c.user.id,
        )  # fmt: skip


# --- measures -------------------------------------------------------------------------------


async def days_to_close(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP6.M1 Days to close (median, from the month's end to the close completing)."""
    done = [
        (c.completed_at.date() - agents.period_end(c.selection["period"])).days
        for c in cases
        if c.completed_at is not None and c.selection.get("period")
    ]
    return Decimal(str(round(statistics.median(done), 1))) if done else None


async def reconciling_items(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP6.M2 Reconciling items (per close: differences explained, statement gaps)."""
    if not cases:
        return None
    rows = list(
        await session.execute(
            select(PodCaseStep.l5_code, PodCaseStep.result).where(
                PodCaseStep.case_id.in_([c.id for c in cases]),
                PodCaseStep.l5_code.in_(["6.1.2.b", "6.1.3.a"]),
                PodCaseStep.status == StepStatus.DONE,
            )
        )
    )
    if not rows:
        return None
    count = 0
    for code, body in rows:
        if code == "6.1.2.b":
            count += len(Explanation.model_validate(body).items)
        else:
            count += StatementCheck.model_validate(body).gaps
    return Decimal(str(round(count / len(cases), 1)))


async def audit_findings(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AP6.M3 Audit findings (review tasks raised on closes: deadlines missed, the daily
    reconciliation moving)."""
    if not cases:
        return None
    found = await session.scalar(
        select(func.count())
        .select_from(PodReviewTask)
        .where(PodReviewTask.case_id.in_([c.id for c in cases]))
    )
    return Decimal(found or 0)


# --- daily: subledger vs ledger, and the close deadline ----------------------------------------


async def newest_snapshot(session: AsyncSession, case: PodCase) -> PodSnapshot | None:
    """The newest snapshot in use of the case's entity and company that has the ledgers."""
    own = await session.get(PodSnapshot, case.snapshot_id)
    if own is None:
        return None
    archived = select(PodSnapshotArchive.snapshot_id)
    candidates = await session.scalars(
        select(PodSnapshot)
        .where(
            PodSnapshot.entity_id == case.entity_id,
            PodSnapshot.company_id == own.company_id,
            PodSnapshot.id.not_in(archived),
        )
        .order_by(PodSnapshot.as_of.desc(), PodSnapshot.created_at.desc())
    )
    return next((s for s in candidates if "ledger_balances" in s.coverage), None)


def _finding(session: AsyncSession, case: PodCase, subject: str, detail: str) -> None:
    session.add(
        PodReviewTask(case_id=case.id, kind=ReviewTaskKind.OTHER, subject=subject,
                      detail=detail, blocking=False, created_by=None)
    )  # fmt: skip


async def _has_open(session: AsyncSession, case: PodCase, subject: str) -> bool:
    found = await session.scalar(
        select(PodReviewTask.id).where(
            PodReviewTask.case_id == case.id,
            PodReviewTask.subject == subject,
            PodReviewTask.status == ReviewTaskStatus.OPEN,
        )
    )
    return found is not None


async def check_close(session: AsyncSession, case: PodCase, today: date) -> None:
    """One close, one day: the reconciliation again on the newest snapshot (6.1.2.a daily),
    and the deadline (AP6.R1). Before sign-off a change raises a finding for the controller;
    after it only the execution record moves (an approval binds its content)."""
    snapshot = await newest_snapshot(session, case)
    if snapshot is not None:
        try:
            comparison, items, unexplained = agents.reconcile(snapshots.document(snapshot))
        except StepFailedError:
            comparison = None
        if comparison is not None:
            differences = [str(x.difference) for x in comparison.comparisons]
            daily = {
                "date": today.isoformat(), "snapshot_id": str(snapshot.id),
                "as_of": comparison.as_of.isoformat(), "unexplained": str(unexplained),
                "differences": differences,
                "items": len(items),
            }  # fmt: skip
            before = case.state.get("_daily")
            moved = before is not None and (
                before["unexplained"], before["differences"]
            ) != (daily["unexplained"], daily["differences"])  # fmt: skip
            case.state = {**case.state, "_daily": daily}
            if moved and case.status == CaseStatus.DRAFT:
                _finding(session, case, "Reconciliation moved",
                         f"On {snapshot.as_of} the subledger-to-ledger difference is "
                         f"{', '.join(differences)} (unexplained {unexplained}): "
                         "redo 6.1.2 on a refreshed source.")  # fmt: skip
    period = case.selection["period"]
    days = int((case.state.get("policy", {}).get("values") or {}).get("close_day", 5))
    due = deadline(period, days)
    unposted = await session.scalar(
        select(func.count())
        .select_from(PodPostingTask)
        .where(
            PodPostingTask.case_id == case.id,
            PodPostingTask.kind == TaskKind.CREATE_JOURNAL_ENTRY,
            PodPostingTask.external_txn_id.is_(None),
        )
    )
    late = today > due and (case.status == CaseStatus.DRAFT or bool(unposted))
    if not late:
        return
    case.state = {**case.state, "_deadline_missed": due.isoformat()}
    if case.status == CaseStatus.DRAFT and not await _has_open(session, case, "Close deadline"):
        _finding(session, case, "Close deadline",
                 f"{period}'s accruals were due in the ledger by {due} and the close isn't "
                 "signed off: finish the review and sign off (AP6.R1).")  # fmt: skip


@jobs.daily(DAILY_JOB)
@jobs.handler(DAILY_JOB)
async def daily_check(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    open_closes = list(
        await session.scalars(
            select(PodCase).where(
                PodCase.workflow == KEY,
                PodCase.status.in_([CaseStatus.DRAFT, CaseStatus.APPROVED]),
            )
        )
    )
    today = utcnow().date()
    for case in open_closes:
        await check_close(session, case, today)
