"""Demo data from the app (for a fresh or production database) and sample invoices written
from a PO (instead of uploading one)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.llm.base import LLMError
from src.app.finance_pod import demo
from src.app.finance_pod.invoices import sample
from src.app.finance_pod.mail import FpEmail
from src.app.finance_pod.orders.models import FpPurchaseOrder
from src.app.finance_pod.reference.models import FpVendor
from src.app.finance_pod.settings.service import current
from tests.conftest import FakeLLM
from tests.finance_pod.conftest import upload

FP = "/api/v1/finance-pod"


async def no_download(session: AsyncSession, data: bytes | None = None) -> int:
    raise RuntimeError("offline")


async def test_demo_data_loads_once_and_runs_end_to_end(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(demo.sanctions, "load", no_download)
    r = await fpod.post(f"{FP}/demo-data")
    assert r.status_code == 200, r.text
    first = r.json()
    assert len(first["loaded"]) == 6 and not first["skipped"]
    assert any("second person go to" in n for n in first["notes"])
    assert any("sanctions list couldn't be downloaded" in n for n in first["notes"])
    assert (await db.scalar(select(FpEmail.id))) is None  # nothing was emailed

    again = (await fpod.post(f"{FP}/demo-data")).json()
    assert again["loaded"] == [] and len(again["skipped"]) == 6

    # What it loaded works: a payment run with a call-back, a decision for the controller,
    # an invoice in the billing analyst's queue
    run = (await fpod.post(f"{FP}/payment-runs")).json()
    assert any(i["callback_status"] == "needed" for i in run["items"])
    [meridian] = [
        a for a in (await fpod.get(f"{FP}/client-applications")).json() if a["status"] == "proposed"
    ]
    detail = (await fpod.get(f"{FP}/client-applications/{meridian['id']}")).json()
    assert detail["can_decide"] is None  # opened by the other admin: this one decides
    assert len((await fpod.get(f"{FP}/sales-invoices?status=review")).json()) == 1


async def test_a_single_finance_admin_is_told_to_add_a_second_one(
    fpod: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demo.sanctions, "load", no_download)
    r = await fpod.post(f"{FP}/demo-data")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "demo_needs_second_admin"
    assert "second Finance Admin" in r.json()["detail"]["message"]
    assert (await db.scalar(select(FpPurchaseOrder.id))) is None  # nothing was loaded

    # With self-approval on, one admin may load it (and is told who approves)
    settings = await current(db)
    settings.allow_self_approval = True
    db.add(settings)
    await db.commit()
    r = await fpod.post(f"{FP}/demo-data")
    assert r.status_code == 200, r.text
    assert any("only Finance Admin" in n for n in r.json()["notes"])


async def test_demo_data_loads_after_the_reference_template_was_uploaded(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The template's example rows include vendor V-FISH but not the demo's other vendors
    monkeypatch.setattr(demo.sanctions, "load", no_download)
    template = (await fpod.get(f"{FP}/reference/template")).content
    assert (await upload(fpod, template)).status_code == 200
    r = await fpod.post(f"{FP}/demo-data")
    assert r.status_code == 200, r.text
    assert any("wasn't there yet" in item for item in r.json()["loaded"])
    vendors = await db.scalars(select(FpVendor))
    by_code = {v.code: v for v in vendors}
    assert {"V-FISH", "V-CHEM", "V-SEQ", "V-HELIX"} <= by_code.keys()
    assert by_code["V-FISH"].email == "orders@labsupply.example"  # what was there is kept


async def test_a_sample_invoice_for_a_po_goes_through_capture(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    db: AsyncSession,
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(demo.sanctions, "load", no_download)
    await fpod.post(f"{FP}/demo-data")
    po = await db.scalar(select(FpPurchaseOrder).where(FpPurchaseOrder.vendor_code == "V-CHEM"))
    assert po is not None

    _, data, note = await sample.build(db, po, "quantity")
    assert data.startswith(b"%PDF") and po.reference.encode() in data
    assert "2 more than received" in note  # 6 of 12 received: it bills 8

    fake_llm.error = LLMError("offline")  # the reading fails: AP keys the data instead
    r = await fpod.post(f"{FP}/invoices/sample", json={"po_id": str(po.id), "scenario": "price"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert "price variance" in out["note"]
    inv = (await fpod.get(f"{FP}/invoices/{out['invoice_id']}")).json()
    assert inv["status"] == "captured" and inv["filename"].endswith(".pdf")
    assert (
        await fpod.post(f"{FP}/invoices/sample", json={"po_id": str(po.request_id)})
    ).status_code == 422
