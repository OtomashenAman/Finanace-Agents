"""AR Phase 3: billing and invoicing. The report-issued event builds the invoice, the
fee-rule agent prices and checks it, the billing analyst reviews what's flagged, and the
delivery agent posts and sends it (and the monthly statements)."""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.finance_pod.billing import delivery, workbook
from src.app.finance_pod.billing.models import FpFee
from src.app.finance_pod.clients.models import ClientStatus, FpClient, FpClientHistory
from src.app.finance_pod.mail import FpEmail, MailKind

FP = "/api/v1/finance-pod"


async def client(db: AsyncSession, code: str, address: str, **terms: Any) -> None:
    approver = await db.scalar(select(User).limit(1))
    assert approver is not None
    db.add(
        FpClient(
            code=code,
            status=ClientStatus.ACTIVE,
            name=f"Client {code}",
            country="US",
            address=address,
            billing_email=f"ap@{code.lower()}.example",
            currency="USD",
            credit_limit=Decimal("50000"),
            deposit_pct=Decimal("0"),
            payment_terms="Net 30",
            approved_by=approver.id,
            **terms,
        )
    )
    await db.commit()


async def schedule(fpod: AsyncClient) -> None:
    data, _ = workbook.template()
    r = await fpod.post(
        f"{FP}/fee-schedule", files={"file": ("fees.xlsx", data, "application/octet-stream")}
    )
    assert r.status_code == 200, r.text


async def submit(fpod: AsyncClient, code: str, lines: list[dict[str, Any]], **extra: Any) -> Any:
    r = await fpod.post(
        f"{FP}/lab-submissions", json={"client_code": code, "lines": lines, **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_clean_submission_is_invoiced_and_sent_the_same_day(
    fpod: AsyncClient, db: AsyncSession
) -> None:
    await schedule(fpod)
    await client(db, "C-00001", "1 Rittenhouse Sq, Philadelphia PA 19103")
    sub = await submit(
        fpod,
        "C-00001",
        [
            {"item_ref": "D1", "stone_type": "Diamond", "carat": "0.80", "service_code": "grd"},
            {"item_ref": "D2", "stone_type": "diamond", "carat": "1.50", "service_code": "GRD"},
        ],
        estimate="260",
    )
    assert sub["status"] == "in_lab" and sub["reference"].startswith("SUB-")

    r = await fpod.post(f"{FP}/lab-submissions/{sub['id']}/report-issued", json={})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["status"] == "sent"  # nothing unusual: straight through
    assert [(ln["unit_price"], ln["price_source"]) for ln in inv["lines"]] == [
        ("95.00", "schedule"),
        ("160.00", "schedule"),
    ]
    assert (inv["subtotal"], inv["tax_name"], inv["tax"], inv["total"]) == (
        "255.00",
        "Pennsylvania sales tax",
        "15.30",
        "270.30",
    )
    assert inv["due_date"] == (utcnow().date() + timedelta(days=30)).isoformat()

    email = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.CLIENT_INVOICE))
    assert (
        email is not None and email.to_email == "ap@c-00001.example" and email.sent_by is not None
    )
    token = re.search(r"/client-invoice/(\S+)", email.body).group(1)  # type: ignore[union-attr]
    view = (await fpod.get(f"/api/v1/client-invoice/{token}")).json()
    assert (view["reference"], view["total"]) == (inv["reference"], "270.30")
    pdf = await fpod.get(f"/api/v1/client-invoice/{token}/pdf")
    assert pdf.content.startswith(b"%PDF") and inv["reference"].encode() in pdf.content

    # The billing history the monitor reviews from grows by itself
    history = await db.scalar(
        select(FpClientHistory).where(FpClientHistory.invoice_number == inv["reference"])
    )
    assert history is not None and history.amount == Decimal("270.30") and history.paid_on is None
    m = (await fpod.get(f"{FP}/measures/billing")).json()
    assert (m["sent"], m["accurate"], m["straight_through"], m["same_day"]) == (1, 1, 1, 1)


async def test_flagged_items_wait_for_the_billing_analyst_and_overrides_need_a_second_person(
    fpod: AsyncClient, other_admin: AsyncClient, db: AsyncSession
) -> None:
    await schedule(fpod)  # C-00002 has a 15% contract discount on GRD
    await client(db, "C-00002", "5 Park Ave, New York NY 10016")
    sub = await submit(
        fpod,
        "C-00002",
        [
            {"item_ref": "C1", "stone_type": "coloured", "service_code": "CID"},
            {
                "item_ref": "D3",
                "stone_type": "diamond",
                "carat": "0.5",
                "service_code": "GRD",
                "special_price": "60",
                "special_reason": "Launch offer agreed by client services",
            },
            {"item_ref": "D4", "stone_type": "diamond", "carat": "0.5", "service_code": "XRF"},
        ],
        estimate="150",
    )
    performed = [
        {"item_ref": "C1", "service_code": "CID"},
        {"item_ref": "C1", "service_code": "ORG"},  # added in the lab
        {"item_ref": "D3", "service_code": "GRD"},
        {"item_ref": "D4", "service_code": "XRF"},  # not on the schedule
    ]
    r = await fpod.post(
        f"{FP}/lab-submissions/{sub['id']}/report-issued", json={"performed": performed}
    )
    inv = r.json()
    lines = {(ln["item_ref"], ln["service_code"]): ln for ln in inv["lines"]}
    assert inv["status"] == "review"
    assert lines[("D3", "GRD")]["unit_price"] == "80.75"  # 95 less the 15% contract discount
    assert lines[("D3", "GRD")]["override_status"] == "pending"  # the intake special price
    assert lines[("C1", "ORG")]["flags"][0]["key"] == "added_service"
    assert lines[("D4", "XRF")]["price_source"] == "none"
    assert {f["key"] for f in inv["flags"]} == {"above_estimate"}  # 450.75 against 150
    url = f"{FP}/sales-invoices/{inv['id']}"
    assert (await fpod.post(f"{url}/approve")).status_code == 422  # still open items

    # Agents never change the fee schedule
    assert await db.scalar(select(FpFee).where(FpFee.service_code == "XRF")) is None

    await fpod.post(
        f"{url}/override",
        json={
            "line_id": lines[("D4", "XRF")]["id"],
            "price": "40",
            "reason": "XRF screening, agreed rate",
        },
    )
    decide = f"{url}/override/decide"
    assert (
        await fpod.post(decide, json={"line_id": lines[("D4", "XRF")]["id"], "approve": True})
    ).status_code == 403
    r = await other_admin.post(
        decide, json={"line_id": lines[("D4", "XRF")]["id"], "approve": True}
    )
    assert r.status_code == 200, r.text
    r = await fpod.post(
        decide, json={"line_id": lines[("D3", "GRD")]["id"], "approve": True}
    )  # from intake
    assert r.status_code == 200, r.text
    for key, line_id in (("added_service", lines[("C1", "ORG")]["id"]), ("above_estimate", None)):
        r = await fpod.post(
            f"{url}/clear",
            json={"line_id": line_id, "key": key, "note": "Client confirmed by phone"},
        )
        assert r.status_code == 200, r.text
    r = await fpod.post(f"{url}/approve")
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "sent" and done["corrected"] is True
    assert done["subtotal"] == "470.00"  # 120 CID + 250 ORG + 60 special price + 40 override
    m = (await fpod.get(f"{FP}/measures/billing")).json()
    assert (m["sent"], m["accurate"], m["overrides_approved"]) == (1, 0, 2)


async def test_the_lab_system_sends_events_with_its_key(
    fpod: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await schedule(fpod)
    await client(db, "C-00003", "9 Main St, Austin TX 73301")
    received = {
        "event": "submission_received",
        "submission": "LIMS-7781",
        "received": {
            "client_code": "C-00003",
            "turnaround": "express",
            "lines": [{"item_ref": "P1", "stone_type": "pearl", "service_code": "PRL"}],
        },
    }
    assert (await fpod.post("/api/v1/lab-events", json=received)).status_code == 401  # no key set
    monkeypatch.setattr(get_settings(), "lab_events_key", SecretStr("lab-secret"))
    headers = {"X-Lab-Key": "wrong"}
    assert (
        await fpod.post("/api/v1/lab-events", json=received, headers=headers)
    ).status_code == 401
    headers = {"X-Lab-Key": "lab-secret"}
    r = await fpod.post("/api/v1/lab-events", json=received, headers=headers)
    assert r.status_code == 200, r.text
    r = await fpod.post(
        "/api/v1/lab-events",
        json={"event": "report_issued", "submission": "LIMS-7781"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    # No express fee for pearls: the standard fee, flagged; no tax rate for TX: flagged
    assert r.json()["status"] == "review"
    [inv] = (await fpod.get(f"{FP}/sales-invoices")).json()
    detail = (await fpod.get(f"{FP}/sales-invoices/{inv['id']}")).json()
    assert detail["lines"][0]["flags"][0]["key"] == "turnaround"
    assert detail["tax_name"] == "No sales tax"  # the country-wide rate


async def test_monthly_statements_go_once_per_client_and_month(
    fpod: AsyncClient, db: AsyncSession
) -> None:
    await client(db, "C-00004", "1 Elm St, Philadelphia PA 19103")
    db.add(
        FpClientHistory(
            client_code="C-00004",
            invoice_number="SI-00090",
            amount=Decimal("120.00"),
            issued_on=date(2026, 9, 10),
            due_on=date(2026, 10, 10),
            paid_on=None,
        )
    )
    await db.commit()
    ctx = RequestContext(ip=None, user_agent="test")
    first = await delivery.send_statements(db, ctx, actor_id=None, today=date(2026, 11, 1))
    await db.commit()
    again = await delivery.send_statements(db, ctx, actor_id=None, today=date(2026, 11, 1))
    await db.commit()
    assert (first["period"], first["sent"], again["sent"], again["already_sent"]) == (
        "2026-10",
        1,
        0,
        1,
    )
    mail = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.CLIENT_STATEMENT))
    assert mail is not None and mail.sent_by is None  # the delivery agent, on its own


async def test_a_bad_fee_schedule_changes_nothing(fpod: AsyncClient) -> None:
    await schedule(fpod)
    r = await fpod.post(
        f"{FP}/fee-schedule",
        files={"file": ("x.xlsx", b"not a workbook", "application/octet-stream")},
    )
    assert r.status_code == 422
    assert len((await fpod.get(f"{FP}/fee-schedule")).json()["fees"]) == 10
