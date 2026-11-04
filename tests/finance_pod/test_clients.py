"""AR Phase 1: client account and credit set-up. The client applies on the portal, the
onboarding agent checks and sends gaps back, the credit agent proposes, the credit
controller approves, the account agent sets up the ERP and the lab system once, and the
monitor reviews as history builds."""

import json
import re
from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.clients.agents import ClientDocRead
from src.app.finance_pod.clients.models import FpLabClient
from src.app.finance_pod.mail import FpEmail, MailKind
from src.app.main import app
from tests.conftest import FakeLLM

FP = "/api/v1/finance-pod"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # an image: read by the vision model
TODAY = utcnow().date()


def read(**fields: Any) -> dict[str, Any]:
    """What the onboarding agent reads in one document (unset: not on it)."""
    unset = dict.fromkeys(ClientDocRead.model_fields)
    return {**unset, "document_type": "other", **fields}


REGISTRATION = read(document_type="registration", company_name="Helios Diagnostics Inc")
TAX = read(document_type="tax", company_name="Helios Diagnostics Inc", tax_id="12-3456789")
REPORT = read(
    document_type="credit_report",
    company_name="Helios Diagnostics Inc",
    bureau="Dun & Bradstreet",
    report_date=(TODAY - timedelta(days=20)).isoformat(),
    credit_score=82,
    score_max=100,
    risk_rating="Low risk",
    recommended_limit="USD 60,000",
    days_beyond_terms=3,
    legal_filings=0,
    years_in_business=8,
)
REFERENCE = read(
    document_type="trade_reference", referee="Acme Reagents", payment_behaviour="prompt"
)


def form(**changes: Any) -> dict[str, Any]:
    body = {
        "legal_name": "Helios Diagnostics Inc",
        "tax_id": "12-3456789",
        "country": "US",
        "address": "200 Market St, Philadelphia PA",
        "billing_email": "ap@helios.example",
        "contacts": json.dumps(
            [{"name": "Dana Reyes", "email": "dana@helios.example", "role": "Lab manager"}]
        ),
        "currency": "USD",
        "requested_limit": "40000",
        "requested_terms": "Net 45",
        "expected_monthly": "15000",
        "years_trading": "8",
    }
    body.update(changes)
    return body


async def load_sanctions(client: AsyncClient) -> None:
    sdn = b'36,"AERO-CARIBBEAN","-0-","CUBA",-0-\n'
    r = await client.post(
        f"{FP}/onboardings/sanctions/refresh", files={"file": ("sdn.csv", sdn, "text/csv")}
    )
    assert r.status_code == 200, r.text


async def link(db: AsyncSession, kind: MailKind) -> str:
    mail = await db.scalar(
        select(FpEmail).where(FpEmail.kind == kind).order_by(FpEmail.created_at.desc()).limit(1)
    )
    assert mail is not None
    return f"/api/v1/client-portal/{re.search(r'/client-portal/(\S+)', mail.body).group(1)}"  # type: ignore[union-attr]


async def applied(
    fpod: AsyncClient, other: AsyncClient, fake_llm: FakeLLM, db: AsyncSession, *, report: bool
) -> dict[str, Any]:
    """An application sent in full; the agents have checked it and proposed terms."""
    await load_sanctions(fpod)
    app_ = (
        await fpod.post(
            f"{FP}/client-applications",
            json={"client_name": "Helios Diagnostics", "client_email": "dana@helios.example"},
        )
    ).json()
    files = [
        ("registration_file", ("reg.png", PNG + b"r", "image/png")),
        ("tax_file", ("w9.png", PNG + b"t", "image/png")),
    ]
    fake_llm.queue = [REGISTRATION, TAX]
    if report:
        files.append(("credit_report_file", ("dnb.png", PNG + b"c", "image/png")))
        fake_llm.queue.append(REPORT)
    r = await other.post(await link(db, MailKind.CLIENT_INVITE), data=form(), files=files)
    assert r.status_code == 204, r.text
    detail = (await fpod.get(f"{FP}/client-applications/{app_['id']}")).json()
    for c in detail["checks"]:  # read from images: client services confirms by eye
        if c["status"] != "pass" and detail["status"] == "submitted":
            detail = (
                await fpod.post(
                    f"{FP}/client-applications/{app_['id']}/clear",
                    json={"key": c["key"], "note": "Checked against the document."},
                )
            ).json()
    assert detail["status"] == "proposed", detail
    return detail


async def test_the_client_applies_fixes_its_gaps_and_the_controller_approves_credit(
    fpod: AsyncClient, other_admin: AsyncClient, fake_llm: FakeLLM, db: AsyncSession
) -> None:
    await load_sanctions(fpod)
    r = await fpod.post(
        f"{FP}/client-applications",
        json={"client_name": "Helios Diagnostics", "client_email": "Dana@Helios.example"},
    )
    assert r.status_code == 201, r.text
    app_ = r.json()
    assert app_["status"] == "invited" and app_["reference"].startswith("APP-")
    portal = await link(db, MailKind.CLIENT_INVITE)
    assert (await fpod.get(portal)).json()["status"] == "open"

    # --- 1.1: first try: no tax document, and a short tax ID ----------------------------------
    fake_llm.queue = [REGISTRATION]
    r = await other_admin.post(
        portal,
        data=form(tax_id="12-345"),
        files=[("registration_file", ("reg.png", PNG + b"r", "image/png"))],
    )
    assert r.status_code == 204, r.text
    assert (await fpod.get(portal)).status_code == 404  # single use
    detail = (await fpod.get(f"{FP}/client-applications/{app_['id']}")).json()
    assert detail["status"] == "needs_info"
    assert any("tax document" in g for g in detail["gaps"])
    assert any("EIN" in g for g in detail["gaps"])
    again = await link(db, MailKind.CLIENT_GAPS)  # the agent emailed the gaps, a new link
    view = (await fpod.get(again)).json()
    assert view["status"] == "open" and view["documents_held"] == ["registration"]
    assert view["previous"]["legal_name"] == "Helios Diagnostics Inc"
    assert "tax_id" not in view["previous"]

    # --- the client sends the rest; the registration it already sent is kept ----------------
    fake_llm.queue = [REGISTRATION, TAX, REPORT, REFERENCE]
    r = await other_admin.post(
        again,
        data=form(),
        files=[
            ("tax_file", ("w9.png", PNG + b"t", "image/png")),
            ("credit_report_file", ("dnb.png", PNG + b"c", "image/png")),
            ("trade_reference_files", ("ref.png", PNG + b"f", "image/png")),
        ],
    )
    assert r.status_code == 204, r.text
    detail = (await fpod.get(f"{FP}/client-applications/{app_['id']}")).json()
    checks = {c["key"]: c for c in detail["checks"]}
    assert detail["status"] == "submitted" and detail["gaps"] == []
    assert checks["tax_id_matches"]["status"] == "warn"  # read from an image: by eye
    assert checks["sanctions"]["status"] == "pass"
    assert checks["credit_report"]["status"] == "pass"
    assert detail["proposal"] is None  # no credit work until the checks are through

    r = await fpod.post(
        f"{FP}/client-applications/{app_['id']}/clear",
        json={"key": "tax_id_matches", "note": "Same EIN as on the W-9."},
    )
    p = r.json()["proposal"]
    assert r.json()["status"] == "proposed"
    assert (p["risk"], p["decision"], p["credit_limit"], p["payment_terms"]) == (
        "low",
        "credit",
        "40000",
        "Net 30",
    )
    assert p["score"] == 88

    # --- 1.2.2: the credit controller (not who opened it) approves ----------------------------
    terms = {
        "credit_limit": "40000",
        "deposit_pct": "0",
        "payment_terms": "Net 30",
        "currency": "USD",
    }
    url = f"{FP}/client-applications/{app_['id']}/decide"
    assert (await fpod.post(url, json=terms)).status_code == 403  # opened it
    r = await other_admin.post(url, json={**terms, "credit_limit": "30000"})
    assert r.status_code == 422  # a change needs a reason
    r = await other_admin.post(url, json={**terms, "credit_limit": "30000", "note": "New sector."})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["client_code"]) == ("active", "C-00001")
    assert r.json()["changed_from_proposal"] is True

    # --- 1.3.1: one set-up, both systems, and the client told -------------------------------
    [client] = (await fpod.get(f"{FP}/clients")).json()
    assert (client["credit_limit"], client["payment_terms"], client["sync"]["in_sync"]) == (
        "30000.00",
        "Net 30",
        True,
    )
    lab = await db.scalar(select(FpLabClient).where(FpLabClient.client_code == "C-00001"))
    assert lab is not None and (lab.work_status, str(lab.credit_limit)) == ("credit", "30000.00")
    welcome = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.CLIENT_WELCOME))
    assert welcome is not None and welcome.to_email == "ap@helios.example"
    assert "C-00001" in welcome.body and "30,000.00" in welcome.body

    m = (await fpod.get(f"{FP}/measures/clients")).json()
    assert (m["accounts"], m["first_pass_clean"], m["gaps_sent"], m["controller_changes"]) == (
        1,
        0,
        1,
        1,
    )


async def test_no_credit_without_a_report_or_without_a_person(
    fpod: AsyncClient, other_admin: AsyncClient, fake_llm: FakeLLM, db: AsyncSession
) -> None:
    detail = await applied(fpod, other_admin, fake_llm, db, report=False)
    p = detail["proposal"]
    assert (p["decision"], p["credit_limit"], p["deposit_pct"]) == ("deposit", None, "50")
    # Only the controller's decision (and a monitor review's) set credit: no other route
    setting = [
        r.path  # type: ignore[attr-defined]
        for r in app.routes
        if "client" in getattr(r, "path", "") and "POST" in getattr(r, "methods", set())
    ]
    assert not [p for p in setting if "limit" in p or "terms" in p]
    r = await other_admin.post(
        f"{FP}/client-applications/{detail['id']}/decide",
        json={
            "credit_limit": None,
            "deposit_pct": "0",
            "payment_terms": "Due on receipt",
            "currency": "USD",
            "note": "x",
        },
    )
    assert r.status_code == 422  # neither credit nor a deposit


async def test_the_monitor_keeps_the_lab_in_sync_and_proposes_credit_as_history_builds(
    fpod: AsyncClient, other_admin: AsyncClient, fake_llm: FakeLLM, db: AsyncSession
) -> None:
    detail = await applied(fpod, other_admin, fake_llm, db, report=False)
    r = await other_admin.post(
        f"{FP}/client-applications/{detail['id']}/decide",
        json={
            "credit_limit": None,
            "deposit_pct": "50",
            "payment_terms": "Due on receipt",
            "currency": "USD",
        },
    )
    assert r.status_code == 200, r.text

    # Someone changes the client in the lab system directly: the monitor puts it back
    await db.execute(update(FpLabClient).values(billing_email="old@helios.example"))
    await db.commit()
    [client] = (await fpod.get(f"{FP}/clients")).json()
    assert client["sync"]["in_sync"] is False
    assert (await fpod.post(f"{FP}/clients/monitor")).json() == {
        "reviewed": 1,
        "proposed": 0,
        "resynced": 1,
    }
    assert (await fpod.get(f"{FP}/clients")).json()[0]["sync"]["in_sync"] is True

    # Seven months of invoices, all paid on time: the monitor proposes credit
    lines = ["Client,Invoice,Amount,Issued,Due,Paid"]
    for i in range(7):
        back = TODAY.year * 12 + TODAY.month - 1 - (7 - i)  # the 1st of each of 7 months
        issued = TODAY.replace(year=back // 12, month=back % 12 + 1, day=1)
        due = issued + timedelta(days=15)
        lines.append(f"C-00001,H-{i},{4000 + i * 500},{issued},{due},{due - timedelta(days=2)}")
    lines.append("C-99999,X-1,10,2026-01-01,2026-01-15,")
    r = await fpod.post(
        f"{FP}/clients/history",
        files={"file": ("history.csv", "\n".join(lines).encode(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert (result["rows"], result["monitor"]["proposed"], len(result["skipped"])) == (7, 1, 1)
    [review] = (await fpod.get(f"{FP}/credit-reviews?open_only=true")).json()
    assert review["proposal"]["proposed"]["credit_limit"] == "14000"  # twice the busiest month
    assert (await fpod.get(f"{FP}/clients")).json()[0]["credit_limit"] is None  # not yet

    r = await other_admin.post(
        f"{FP}/credit-reviews/{review['id']}/decide", json={"approve": True, "note": ""}
    )
    assert r.json()["status"] == "approved"
    [client] = (await fpod.get(f"{FP}/clients")).json()
    assert (client["credit_limit"], client["deposit_pct"], client["payment_terms"]) == (
        "14000.00",
        "0.00",
        "Net 30",
    )
    lab = await db.scalar(select(FpLabClient))
    await db.refresh(lab)  # type: ignore[arg-type]
    assert lab is not None and lab.work_status == "credit"
