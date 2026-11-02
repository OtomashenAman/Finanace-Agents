"""Posting an approved task to the ERP the case's snapshot was read from (ERPNext).

A person clicks post; the app creates the document with our reference (the task key) in
`finance_acc_ref`, submits it when the doctype is submittable, and records its ERP name.
The task is then recorded, not verified: only a later snapshot of the same company that
contains the document verifies it, as for a manual posting.

Retrying is safe: the document is looked up by our reference first, so a post whose answer
was lost finds what the first attempt created instead of creating a second.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.data_sources import erpnext_service
from src.app.data_sources.models import SourceKind
from src.app.data_sources.providers.erpnext import REF_FIELD, ErpNextError
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind


@dataclass(frozen=True)
class ErpTarget:
    doctype: str
    submit: bool  # submittable documents are submitted once created


ERP_KINDS: dict[TaskKind, ErpTarget] = {
    TaskKind.CREATE_SUPPLIER: ErpTarget("Supplier", submit=False),
    TaskKind.CREATE_PURCHASE_ORDER: ErpTarget("Purchase Order", submit=True),
    TaskKind.CREATE_PURCHASE_RECEIPT: ErpTarget("Purchase Receipt", submit=True),
}


class PostingError(Exception):
    """Why the post didn't happen (the task stays proposed; retrying is safe)."""


def instructions_doc(task: PodPostingTask) -> dict[str, Any]:
    doc = task.instructions.get("doc")
    if not isinstance(doc, dict) or not doc:
        raise PostingError("The task has no ERP document to post.")
    return {k: v for k, v in doc.items() if k not in ("doctype", "name", REF_FIELD, "docstatus")}


async def post(session: AsyncSession, task: PodPostingTask, case: PodCase) -> str:
    """Create (or find) and submit the task's document; returns its ERP name."""
    target = ERP_KINDS.get(task.kind)
    if target is None:
        raise PostingError("Only ERP postings can be posted by the app.")
    source = await snapshots.source_of(session, case.snapshot_id)
    if source is None or source.kind != SourceKind.ERPNEXT:
        raise PostingError("The case's snapshot wasn't read from a connected ERPNext.")
    doc = instructions_doc(task)
    try:
        async with erpnext_service.erpnext_api(source) as api:
            found = await api.find_by_ref(target.doctype, task.task_key)
            if found is None:
                created = await api.insert(
                    {**doc, "doctype": target.doctype, REF_FIELD: task.task_key}
                )
                name, docstatus = str(created["name"]), int(created.get("docstatus") or 0)
            else:
                name, docstatus = str(found["name"]), int(found.get("docstatus") or 0)
            if target.submit and docstatus == 0:
                await api.submit(target.doctype, name)
    except (ErpNextError, erpnext_service.ErpNextConnectionError) as exc:
        message = exc.message if isinstance(exc, erpnext_service.ErpNextConnectionError) else exc
        raise PostingError(
            f"{message} Retrying is safe: it finds anything already created."
        ) from exc
    return name


def present(task: PodPostingTask, doc: SnapshotDocument) -> bool:
    """The fresh snapshot holds the posted document (a submitted one when it must be)."""
    txn = task.external_txn_id
    if task.kind == TaskKind.CREATE_SUPPLIER:
        return any(v.id == txn for v in doc.vendors or [])
    if task.kind == TaskKind.CREATE_PURCHASE_ORDER:
        return any(o.id == txn and o.doc_status == "Submitted" for o in doc.purchase_orders or [])
    if task.kind == TaskKind.CREATE_PURCHASE_RECEIPT:
        return any(r.id == txn and r.doc_status == "Submitted" for r in doc.purchase_receipts or [])
    return False
