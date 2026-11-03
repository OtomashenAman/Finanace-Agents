"""The Finance POD's own endpoints around a case: the snapshots a person may open a case on,
documents, the mail the agents draft (sent by a person holding the purpose's capacity) and
the ERP postings (posted and verified by the task kind's capacity)."""

import re
import uuid
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Form, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.core.errors import AppError
from src.app.finance_pod.access import FinanceAccessDep
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.messaging import service as messaging
from src.app.service_pod.core.messaging.models import ArtifactKind, PodArtifact, PodMessage
from src.app.service_pod.core.messaging.schemas import (
    ArtifactOut,
    MessageOut,
    MessageSend,
    MessageUpdate,
)
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import Collection, SnapshotDocument
from src.app.service_pod.core.snapshots.exceptions import SnapshotTooLargeError
from src.app.service_pod.core.snapshots.schemas import SnapshotSummary
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import PodPostingTask
from src.app.service_pod.core.tasks.schemas import TaskAction, TaskOut
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey, WorkflowKey

router = APIRouter(tags=["finance pod: cases"])
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 422)
}
FINANCE_DOCUMENTS = (
    ArtifactKind.INVOICE_COPY,
    ArtifactKind.QUOTE, ArtifactKind.TAX_FORM, ArtifactKind.BANK_LETTER,
    ArtifactKind.COMPLIANCE, ArtifactKind.VENDOR_STATEMENT, ArtifactKind.SUPPORTING,
    ArtifactKind.OTHER,
)  # fmt: skip


class CapacityRequiredError(AppError):
    status_code = 403
    code = "capacity_required"


@router.get("/sources", response_model=list[SnapshotSummary])
async def sources(
    session: SessionDep, access: FinanceAccessDep, workflow: WorkflowKey
) -> list[SnapshotSummary]:
    """Snapshots a case of this workflow can open on: they supply what it needs, aren't
    archived, and belong to an entity you may open it for. Newest first."""
    spec = WORKFLOWS[workflow]
    if spec.pod != PodKey.FINANCE:
        return []
    out = []
    for snap in await snapshots.list_snapshots(session, None):
        covered = spec.required <= {Collection(c) for c in snap.coverage}
        if covered and access.holds_any(set(spec.plan.openers), snap.entity.id):
            out.append(snap)
    return out


class CatalogueItem(BaseModel):
    code: str
    name: str
    group: str
    catalogue_rate: Decimal | None
    contract_rates: dict[str, Decimal]  # vendor id -> contract price


class CatalogueEntry(BaseModel):
    id: str
    name: str
    detail: str | None = None


class Catalogue(BaseModel):
    currency: str
    items: list[CatalogueItem]
    vendors: list[CatalogueEntry]  # detail: status
    cost_centres: list[CatalogueEntry]
    labs: list[CatalogueEntry]
    grants: list[CatalogueEntry]  # detail: period and restriction
    purchase_requests: list[CatalogueEntry]  # the ERP's own, a request can start from
    incoming_invoices: list[CatalogueEntry]  # ERPNext drafts a matching case can start from
    # Lab submissions whose report is issued and aren't billed (a billing case starts from one)
    billable_submissions: list[CatalogueEntry] = []


@router.get("/cases/{case_id}/sources", response_model=list[SnapshotSummary], responses=_ERRORS)
async def case_sources(
    case_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> list[SnapshotSummary]:
    """Snapshots this case can be verified against or moved to: its entity's, supplying what
    its workflow needs, newest first. For anyone working on the case (a buyer verifying a PO
    may not be someone who opens requests)."""
    case = await load_case(session, case_id, access=access)
    spec = WORKFLOWS[case.workflow]
    return [
        snap
        for snap in await snapshots.list_snapshots(session, case.entity_id)
        if spec.required <= {Collection(c) for c in snap.coverage}
    ]


@router.get("/cases/{case_id}/catalogue", response_model=Catalogue, responses=_ERRORS)
async def catalogue(case_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep) -> Catalogue:
    """The master data of the case's snapshot people pick from (items, vendors, coding)."""
    case = await load_case(session, case_id, access=access)
    snapshot = await snapshots.load_snapshot(session, case.snapshot_id)
    return _catalogue(snapshots.document(snapshot))


@router.get("/sources/{snapshot_id}/catalogue", response_model=Catalogue, responses=_ERRORS)
async def source_catalogue(
    snapshot_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep, workflow: WorkflowKey
) -> Catalogue:
    """The same, for a snapshot you may open a case on (to start from an ERP request)."""
    if snapshot_id not in {s.id for s in await sources(session, access, workflow)}:
        raise messaging.ArtifactNotFoundError("Snapshot not found.")
    found = _catalogue(snapshots.document(await snapshots.load_snapshot(session, snapshot_id)))
    if workflow == WorkflowKey.AP_INVOICE_MATCH:
        # An invoice that already has a live matching case can't start another
        taken = set(
            await session.scalars(
                select(PodCase.selection["bill_id"].astext).where(
                    PodCase.workflow == workflow, PodCase.status != CaseStatus.CANCELLED
                )
            )
        )
        found.incoming_invoices = [b for b in found.incoming_invoices if b.id not in taken]
    if workflow == WorkflowKey.AR_BILLING:
        from src.app.finance_pod.flows.ar_billing.service import live_cases, to_bill

        doc = snapshots.document(await snapshots.load_snapshot(session, snapshot_id))
        names = {c.id: c.name for c in doc.clients or []}
        found.billable_submissions = [
            CatalogueEntry(
                id=s.id,
                name=names.get(s.client_id, s.client_id),
                detail=f"report issued {s.report_issued_on}, {doc.currency} {s.total:,.2f}",
            )
            for s in to_bill(doc, await live_cases(session))
        ]
    return found


def _catalogue(doc: SnapshotDocument) -> Catalogue:
    prices = doc.item_prices or []
    return Catalogue(
        currency=doc.currency,
        items=[
            CatalogueItem(
                code=i.code, name=i.name, group=i.group,
                catalogue_rate=next((p.rate for p in prices
                                     if p.item_code == i.code and p.vendor_id is None), None),
                contract_rates={p.vendor_id: p.rate for p in prices
                                if p.item_code == i.code and p.vendor_id},
            )
            for i in doc.items or []
        ],
        vendors=[CatalogueEntry(id=v.id, name=v.name, detail=v.status) for v in doc.vendors or []],
        cost_centres=[CatalogueEntry(id=x.id, name=x.name) for x in doc.cost_centres or []],
        labs=[CatalogueEntry(id=x.id, name=x.name) for x in doc.labs or []],
        grants=[
            CatalogueEntry(
                id=g.id, name=g.name,
                detail=" · ".join(filter(None, [
                    f"{g.start_date or '?'} to {g.end_date or '?'}",
                    "restricted: " + ", ".join(g.allowed_item_groups) if g.restricted else None,
                ])),
            )
            for g in doc.grants or []
        ],
        purchase_requests=[
            CatalogueEntry(id=r.id, name=r.title or r.id, detail=f"{r.status}, {r.date}")
            for r in doc.purchase_requests or [] if r.doc_status == "Submitted"
        ],
        incoming_invoices=[
            CatalogueEntry(id=b.id, name=f"{b.vendor_id} {b.bill_number or ''}".strip(),
                           detail=f"{doc.currency} {b.total:,.2f}, {b.bill_date or b.posting_date}")
            for b in doc.bills or [] if b.doc_status == "Draft" and b.return_against is None
        ],
    )  # fmt: skip


@router.post(
    "/cases/{case_id}/artifacts",
    response_model=ArtifactOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def upload_document(
    case_id: uuid.UUID,
    file: UploadFile,
    kind: Annotated[ArtifactKind, Form()],
    session: SessionDep,
    access: FinanceAccessDep,
    ctx: RequestContextDep,
) -> ArtifactOut:
    """A document for the case (a quote, compliance papers...). Tax forms and bank letters
    count only when the vendor uploads them through the portal."""
    if kind not in FINANCE_DOCUMENTS:
        raise CapacityRequiredError("That kind of document isn't used in the Finance POD.")
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise SnapshotTooLargeError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    return await messaging.upload_artifact(
        session, access, case_id, kind, [], file.filename or "document",
        file.content_type or "application/octet-stream", data, ctx,
    )  # fmt: skip


@router.get("/artifacts/{artifact_id}/content", responses=_ERRORS)
async def document_content(
    artifact_id: uuid.UUID, session: SessionDep, access: FinanceAccessDep
) -> Response:
    artifact = await session.get(PodArtifact, artifact_id)
    if artifact is None:
        raise messaging.ArtifactNotFoundError
    await load_case(session, artifact.case_id, access=access)  # 404 unless you see the case
    artifact, content = await messaging.artifact_content(session, artifact_id)
    return Response(
        content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{re.sub(r"[^A-Za-z0-9._-]", "_", artifact.filename)}"; '
                f"filename*=UTF-8''{quote(artifact.filename)}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _message_case(
    session: SessionDep, access: PodAccess, message_id: uuid.UUID
) -> tuple[PodMessage, PodCase]:
    message = await session.get(PodMessage, message_id)
    if message is None:
        raise messaging.MessageNotFoundError
    case = await load_case(session, message.case_id, access=access)
    senders = WORKFLOWS[case.workflow].plan.senders.get(message.purpose, frozenset())
    if not access.holds_any(set(senders), case.entity_id):
        who = ", ".join(sorted(s.replace("_", " ") for s in senders)) or "nobody"
        raise CapacityRequiredError(f"This mail is sent by: {who}.")
    return message, case


@router.patch("/messages/{message_id}", response_model=MessageOut, responses=_ERRORS)
async def edit_message(
    message_id: uuid.UUID,
    body: MessageUpdate,
    session: SessionDep,
    access: FinanceAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    await _message_case(session, access, message_id)
    return await messaging.update_message(session, access, message_id, body, ctx)


@router.post("/messages/{message_id}/send", response_model=MessageOut, responses=_ERRORS)
async def send_message(
    message_id: uuid.UUID,
    body: MessageSend,
    session: SessionDep,
    access: FinanceAccessDep,
    ctx: RequestContextDep,
) -> MessageOut:
    """Approve the exact message and send it once (the agent drafted it)."""
    await _message_case(session, access, message_id)
    return await messaging.send_message(session, access, message_id, body, ctx)


@router.post("/tasks/{task_id}/actions", response_model=TaskOut, responses=_ERRORS)
async def task_action(
    task_id: uuid.UUID,
    body: TaskAction,
    session: SessionDep,
    access: FinanceAccessDep,
    ctx: RequestContextDep,
) -> TaskOut:
    """Post an approved ERP task, verify it against a fresh snapshot, or cancel it."""
    task = await session.get(PodPostingTask, task_id)
    if task is None:
        raise tasks.TaskNotFoundError
    case = await load_case(session, task.case_id, access=access)
    posters = WORKFLOWS[case.workflow].plan.posters.get(task.kind.value, frozenset())
    if not access.holds_any(set(posters), case.entity_id):
        who = ", ".join(sorted(s.replace("_", " ") for s in posters)) or "nobody"
        raise CapacityRequiredError(f"This posting is handled by: {who}.")
    return await tasks.run_action(session, access, task_id, body, ctx)
