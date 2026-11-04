"""Phase 1.3-1.6: sourcing, vendor onboarding through the portal, the purchase order, and
the measures. Mail goes to the outbox (simulated) in tests."""

import re
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.mail import FpEmail, MailKind
from src.app.main import app
from tests.conftest import FakeLLM
from tests.finance_pod.conftest import SHEETS, request_body, upload, workbook

FP = "/api/v1/finance-pod"
BASE = f"{FP}/requests"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # recognised as an image: goes to the vision model
REPLY_BY = (utcnow().date() + timedelta(days=7)).isoformat()
ROUTING = "021000021"  # a valid ABA checksum


async def approved(fpod: AsyncClient, other_admin: AsyncClient, **changes: Any) -> dict[str, Any]:
    r = await fpod.post(BASE, json=request_body(**changes))
    pr = r.json()
    r = await fpod.post(f"{BASE}/{pr['id']}/submit", json={"expected_version": pr["version"]})
    pr = r.json()
    ack = bool([f for f in pr["budget_check"]["findings"] if f["severity"] == "acknowledge"])
    r = await other_admin.post(
        f"{BASE}/{pr['id']}/decide",
        json={
            "expected_version": pr["version"],
            "decision": "approve",
            "note": "ok" if ack else "",
            "acknowledge_budget": ack,
        },
    )
    assert r.json()["status"] == "approved", r.text
    return r.json()


async def po_of(client: AsyncClient, pr: dict[str, Any]) -> dict[str, Any]:
    return (await client.get(f"{BASE}/{pr['id']}/po")).json()


async def act(client: AsyncClient, po: dict[str, Any], action: str, **body: Any) -> Any:
    fresh = (await client.get(f"{FP}/purchase-orders/{po['id']}")).json()
    return await client.post(
        f"{FP}/purchase-orders/{po['id']}/{action}",
        json={"expected_version": fresh["version"], **body},
    )


async def test_below_threshold_a_contract_vendor_goes_straight_to_an_issued_po(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    pr = await approved(fpod, other_admin)
    s = (await fpod.get(f"{BASE}/{pr['id']}/sourcing")).json()
    assert s["quotes_needed"] == 0
    [cand] = s["candidates"]
    assert (cand["vendor_code"], cand["covers_all_lines"], cand["contract_total"]) == (
        "V-LAB",
        True,
        "425.00",
    )
    assert s["comparison"][0]["option"] == "contract"
    assert "lowest price" in s["comparison"][0]["flags"]

    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/choose",
        json={"contract_vendor_code": "V-LAB", "payment_terms": "Net 30"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "chosen"
    assert r.json()["justification"].startswith("Contract prices")

    r = await fpod.post(f"{BASE}/{pr['id']}/po")
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["lines"][0]["price_source"] == "contract"
    assert (po["total"], po["grant_code"], po["payment_terms"]) == ("425.00", "GR-22", "Net 30")
    assert po["issues"] == []

    r = await act(fpod, po, "confirm")  # below the PO limit (50000): no approval
    assert r.json()["status"] == "approved"
    r = await act(fpod, po, "issue")
    assert r.status_code == 200, r.text
    issued = r.json()
    assert (issued["status"], issued["erp_system"], issued["erp_ref"]) == (
        "issued",
        "local",
        issued["reference"],
    )
    assert (await fpod.get(f"{BASE}/{pr['id']}")).json()["status"] == "ordered"

    r = await fpod.post(
        f"{FP}/purchase-orders/{po['id']}/acknowledge",
        data={"expected_version": str(issued["version"]), "note": "Confirmed by reply"},
    )
    assert r.json()["status"] == "acknowledged"

    m = (await fpod.get(f"{FP}/measures")).json()
    assert m["cycle"]["count"] == 1
    assert (m["submitted"], m["reworked"]) == (1, 0)


async def test_above_threshold_quotes_are_requested_compared_and_a_new_vendor_is_onboarded(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    reference: None,
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    pr = await approved(
        fpod,
        other_admin,
        lines=[
            {
                "description": "Sequencer service visit",
                "quantity": "1",
                "unit_price": "18000",
                "category": "lab supplies",
            }
        ],
    )
    s = (await fpod.get(f"{BASE}/{pr['id']}/sourcing")).json()
    assert s["quotes_needed"] == 3

    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/quote-requests",
        json={
            "vendors": [
                {"vendor_code": "V-LAB"},
                {"vendor_name": "Helix Services", "vendor_email": "sales@helix.example"},
            ],
            "reply_by": REPLY_BY,
        },
    )
    assert r.status_code == 200, r.text
    s = r.json()
    assert [q["status"] for q in s["quotes"]] == ["requested", "requested"]
    assert len(s["emails"]) == 2
    assert "Sequencer service visit" in s["emails"][0]["body"]
    assert "18000" not in s["emails"][0]["body"]  # vendors never see our estimate

    lab, helix = s["quotes"]
    await fpod.put(
        f"{BASE}/{pr['id']}/sourcing/quotes/{lab['id']}",
        json={"total": "19500", "lead_time_days": 30, "payment_terms": "Net 30"},
    )
    await fpod.put(
        f"{BASE}/{pr['id']}/sourcing/quotes/{helix['id']}",
        json={"total": "17200", "lead_time_days": 10, "payment_terms": "Net 45"},
    )
    s = (await fpod.get(f"{BASE}/{pr['id']}/sourcing")).json()
    rows = {r["vendor_name"]: r for r in s["comparison"]}
    assert rows["Helix Services"]["flags"][:2] == ["lowest price", "fastest"]
    assert "new vendor: onboarding needed" in rows["Helix Services"]["flags"]

    choose = {"quote_id": helix["id"], "payment_terms": "Net 45"}
    r = await fpod.post(f"{BASE}/{pr['id']}/sourcing/choose", json=choose)
    assert r.status_code == 422  # 2 of 3 quotes: needs a justification
    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/choose",
        json={**choose, "justification": "Only two service providers cover this model"},
    )
    assert r.json()["status"] == "awaiting_vendor"
    assert (await fpod.post(f"{BASE}/{pr['id']}/po")).status_code == 409  # not onboarded yet

    # --- 1.5: the vendor uses the portal link from the email ----------------------------------
    invite = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.PORTAL_INVITE))
    assert invite is not None and invite.to_email == "sales@helix.example"
    token = re.search(r"/vendor-portal/(\S+)", invite.body).group(1)  # type: ignore[union-attr]
    portal = f"/api/v1/vendor-portal/{token}"
    assert (await fpod.get(portal)).json()["status"] == "open"

    fake_llm.queue = [
        {
            "document_type": "W-9",
            "legal_name": "Helix Services LLC",
            "tax_id": "12-3456789",
            "address": "1 Main St",
            "bank_name": None,
            "account_name": None,
            "routing_number": None,
            "account_number": None,
            "on_bank_letterhead": None,
            "signed": True,
        },
        {
            "document_type": "bank_letter",
            "legal_name": None,
            "tax_id": None,
            "address": None,
            "bank_name": "First Bank",
            "account_name": "Helix Services LLC",
            "routing_number": ROUTING,
            "account_number": "987654321",
            "on_bank_letterhead": True,
            "signed": True,
        },
    ]
    form = {
        "legal_name": "Helix Services LLC",
        "tax_id": "12-3456789",
        "tax_form": "W-9",
        "address": "1 Main St, Springfield",
        "phone": "+1 555 0100",
        "bank_name": "First Bank",
        "account_name": "Helix Services LLC",
        "routing_number": ROUTING,
        "account_number": "987654321",
    }
    files = {
        "tax_form_file": ("w9.png", PNG, "image/png"),
        "bank_letter_file": ("bank.png", PNG + b"1", "image/png"),
    }
    r = await other_admin.post(portal, data=form, files=files)
    assert r.status_code == 204, r.text
    assert fake_llm.images[-2:] == [1, 1]  # both read as images (vision)
    assert (await fpod.post(portal, data=form, files=files)).status_code == 404  # single use

    [ob] = (await fpod.get(f"{FP}/onboardings")).json()
    detail = (await fpod.get(f"{FP}/onboardings/{ob['id']}")).json()
    assert detail["account_masked"] == "•••••4321"
    checks = {c["key"]: c for c in detail["checks"]}
    assert checks["tax_id_format"]["status"] == "pass"
    assert checks["routing_checksum"]["status"] == "pass"
    assert checks["tax_id_matches_form"]["status"] == "warn"  # read from an image
    assert checks["sanctions"]["status"] == "fail"  # no list loaded yet
    assert detail["can_verify"] is not None

    sdn = b'36,"AERO-CARIBBEAN","-0-","CUBA",-0-\n2674,"HELIX TRADING CO","-0-","SDGT",-0-\n'
    r = await fpod.post(
        f"{FP}/onboardings/sanctions/refresh", files={"file": ("sdn.csv", sdn, "text/csv")}
    )
    assert r.json()["entries"] == 2
    fake_llm.queue = [  # the re-check reads both documents again
        {
            "document_type": "W-9",
            "legal_name": "Helix Services LLC",
            "tax_id": "12-3456789",
            "address": None,
            "bank_name": None,
            "account_name": None,
            "routing_number": None,
            "account_number": None,
            "on_bank_letterhead": None,
            "signed": True,
        },
        {
            "document_type": "bank_letter",
            "legal_name": None,
            "tax_id": None,
            "address": None,
            "bank_name": "First Bank",
            "account_name": "Helix Services LLC",
            "routing_number": ROUTING,
            "account_number": "987654321",
            "on_bank_letterhead": True,
            "signed": True,
        },
    ]
    detail = (await fpod.post(f"{FP}/onboardings/{ob['id']}/recheck")).json()
    checks = {c["key"]: c for c in detail["checks"]}
    assert checks["sanctions"]["status"] == "pass"  # "Helix Trading Co" isn't Helix Services

    for key in ("tax_id_matches_form", "bank_matches_letter"):
        r = await fpod.post(
            f"{FP}/onboardings/{ob['id']}/clear",
            json={"key": key, "note": "Compared the scan by eye: same"},
        )
        assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["can_verify"] is None

    callback = {
        "phone": "+1 555 0100",
        "source": "vendor's official website",
        "contact": "Dana, accounts",
        "confirmed_last4": "4321",
    }
    r = await fpod.post(f"{FP}/onboardings/{ob['id']}/verify", json=callback)
    assert r.status_code == 422  # the number the vendor just gave
    r = await fpod.post(
        f"{FP}/onboardings/{ob['id']}/verify",
        json={**callback, "phone": "+1 555 0199", "confirmed_last4": "0000"},
    )
    assert r.status_code == 422  # the account doesn't match
    r = await fpod.post(
        f"{FP}/onboardings/{ob['id']}/verify", json={**callback, "phone": "+1 555 0199"}
    )
    assert r.json()["status"] == "verified"

    assert (await fpod.post(f"{FP}/onboardings/{ob['id']}/activate")).status_code == 403
    r = await other_admin.post(f"{FP}/onboardings/{ob['id']}/activate")
    assert r.status_code == 200, r.text
    vendor_code = r.json()["vendor_code"]
    assert r.json()["status"] == "active"

    s = (await fpod.get(f"{BASE}/{pr['id']}/sourcing")).json()
    assert (s["status"], s["chosen_vendor_code"]) == ("chosen", vendor_code)
    # It keeps what it was chosen for, so the sourcing agent finds it next time
    vendors = (await fpod.get(f"{FP}/reference")).json()["vendors"]
    assert next(v for v in vendors if v["code"] == vendor_code)["categories"] == ["lab supplies"]
    r = await fpod.post(f"{BASE}/{pr['id']}/po")
    assert r.status_code == 201, r.text
    po = r.json()
    assert (po["vendor_name"], po["total"], po["lines"][0]["price_source"]) == (
        "Helix Services LLC",
        "17200.00",
        "quote",
    )


async def test_a_po_above_the_limit_is_approved_by_the_named_approver_not_the_buyer(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    matrix = {
        "Authority matrix": [
            *SHEETS["Authority matrix"][:2],
            ["po", None, 100, "budget@gia.example", "Senior buyer"],
        ]
    }
    assert (await upload(fpod, workbook(matrix))).status_code == 200
    pr = await approved(fpod, other_admin)
    await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/choose",
        json={"contract_vendor_code": "V-LAB", "payment_terms": "Net 30"},
    )
    po = (await fpod.post(f"{BASE}/{pr['id']}/po")).json()
    r = await act(fpod, po, "confirm")
    assert (r.json()["status"], r.json()["approval_capacity"]) == (
        "pending_approval",
        "Senior buyer",
    )
    assert (await act(fpod, po, "issue")).status_code == 409  # not approved yet
    assert (await act(fpod, po, "approve")).status_code == 403  # waits for budget@
    r = await act(other_admin, po, "approve")
    assert r.status_code == 200, r.text
    assert r.json()["approved_by_name"] == "Budget"
    assert (await act(fpod, po, "issue")).json()["status"] == "issued"


async def test_the_sourcing_agent_reads_a_quote_and_its_total_must_be_in_the_text(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, fake_llm: FakeLLM
) -> None:
    pr = await approved(fpod, other_admin)
    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/quotes",
        json={
            "vendor_name": "Pipette Direct",
            "vendor_email": "q@pipette.example",
            "status": "requested",
        },
    )
    quote = r.json()["quotes"][0]
    doc = b"Quote Q-77\nPipette tips x10\nTotal: 410.00 USD\nLead time 2 weeks\nNet 30"
    read = {
        "vendor_name": "Pipette Direct",
        "total": "999.00",
        "currency": "USD",
        "lead_time_days": 14,
        "payment_terms": "Net 30",
        "valid_until": None,
        "quote_reference": "Q-77",
    }
    fake_llm.output = read
    url = f"{BASE}/{pr['id']}/sourcing/quotes/{quote['id']}/file"
    r = await fpod.post(url, files={"file": ("quote.txt", doc, "text/plain")})
    assert r.json()["quotes"][0]["total"] is None  # 999.00 isn't in the text: not used

    fake_llm.output = {**read, "total": "410.00"}
    r = await fpod.post(url, files={"file": ("quote.txt", doc, "text/plain")})
    q = r.json()["quotes"][0]
    assert (q["status"], q["total"], q["lead_time_days"], q["ai_read"]["verified"]) == (
        "received",
        "410.00",
        14,
        True,
    )


async def test_no_po_without_an_approved_request(
    fpod: AsyncClient, reference: None, db: AsyncSession
) -> None:
    r = await fpod.post(BASE, json=request_body())
    draft = r.json()
    assert (await fpod.post(f"{BASE}/{draft['id']}/po")).status_code == 409
    # Even straight into the database, the trigger refuses it
    with pytest.raises(DBAPIError, match="No PO without an approved request"):
        await db.execute(
            text(
                "INSERT INTO fpod_purchase_orders (id, request_id, status, version, vendor_code,"
                " vendor_name, currency, drafted_by, self_approval, created_at, updated_at)"
                " SELECT gen_random_uuid(), id, 'draft', 1, 'V-LAB', 'x', 'USD', requester_id,"
                " false, now(), now() FROM fpod_requests WHERE id = :id"
            ),
            {"id": draft["id"]},
        )
    await db.rollback()


async def test_bank_details_change_only_through_the_portal_with_a_fresh_onboarding(
    fpod: AsyncClient, reference: None
) -> None:
    r = await fpod.post(f"{FP}/onboardings/bank-change", json={"vendor_code": "V-LAB"})
    assert r.status_code == 201, r.text
    ob = r.json()
    assert (ob["kind"], ob["status"], ob["vendor_code"]) == ("bank_change", "invited", "V-LAB")
    assert ob["portal_url"].startswith("http")
    # No endpoint takes bank details except the vendor's portal form
    schemas = app.openapi()["components"]["schemas"]
    taking_accounts = sorted(
        n for n, s in schemas.items() if "account_number" in s.get("properties", {})
    )
    assert len(taking_accounts) == 1 and "portal_submit" in taking_accounts[0]


async def _new_vendor_chosen(
    fpod: AsyncClient, other_admin: AsyncClient, email: str
) -> dict[str, Any]:
    pr = await approved(fpod, other_admin)
    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/quotes",
        json={"vendor_name": "Aman Rajput", "vendor_email": email, "total": "400"},
    )
    quote = r.json()["quotes"][-1]
    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/choose",
        json={"quote_id": quote["id"], "payment_terms": "Net 30"},
    )
    assert r.json()["status"] == "awaiting_vendor", r.text
    return {"pr": pr, "quote": quote, "sourcing": r.json()}


async def test_choosing_again_keeps_or_retires_the_onboarding_instead_of_piling_up(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    first = await _new_vendor_chosen(fpod, other_admin, "ammy@vendor.example")
    pr, quote = first["pr"], first["quote"]
    again = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/choose",
        json={"quote_id": quote["id"], "payment_terms": "Net 45"},
    )
    assert again.json()["onboarding_id"] == first["sourcing"]["onboarding_id"]  # same vendor
    assert len((await fpod.get(f"{FP}/onboardings")).json()) == 1

    # Another vendor (a contract one): the open onboarding is retired, not left dangling
    r = await fpod.post(
        f"{BASE}/{pr['id']}/sourcing/choose",
        json={"contract_vendor_code": "V-LAB", "payment_terms": "Net 30"},
    )
    assert (r.json()["status"], r.json()["onboarding_id"]) == ("chosen", None)
    [ob] = (await fpod.get(f"{FP}/onboardings")).json()
    assert ob["status"] == "rejected"


async def test_an_unreadable_value_needs_an_eye_and_a_bad_submission_goes_back_to_the_vendor(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    reference: None,
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    chosen = await _new_vendor_chosen(fpod, other_admin, "ammy@vendor.example")
    invite = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.PORTAL_INVITE))
    token = re.search(r"/vendor-portal/(\S+)", invite.body).group(1)  # type: ignore[union-attr]
    blank = {
        "document_type": "other",
        "legal_name": None,
        "tax_id": None,
        "address": None,
        "bank_name": None,
        "account_name": None,
        "routing_number": None,
        "account_number": None,
        "on_bank_letterhead": None,
        "signed": None,
    }
    fake_llm.queue = [blank, blank]
    form = {
        "legal_name": "Aman Rajput",
        "tax_id": "9876543",
        "tax_form": "W-9",
        "address": "12 Market Road, Pune",
        "bank_name": "HDFC",
        "account_name": "Aman Rajput",
        "routing_number": "HDFC0001234",
        "account_number": "50100234567",
    }
    files = {
        "tax_form_file": ("w9.png", PNG, "image/png"),
        "bank_letter_file": ("bank.png", PNG + b"2", "image/png"),
    }
    assert (
        await fpod.post(f"/api/v1/vendor-portal/{token}", data=form, files=files)
    ).status_code == 204

    ob_id = chosen["sourcing"]["onboarding_id"]
    checks = {c["key"]: c for c in (await fpod.get(f"{FP}/onboardings/{ob_id}")).json()["checks"]}
    # Nothing read on the documents: a person compares, it's not a "mismatch"
    assert (
        checks["tax_id_matches_form"]["status"],
        checks["tax_id_matches_form"]["clearable"],
    ) == ("unknown", True)
    assert (
        checks["bank_matches_letter"]["status"],
        checks["bank_matches_letter"]["clearable"],
    ) == ("unknown", True)
    # A 7-digit tax ID is wrong whatever the documents say
    assert (checks["tax_id_format"]["status"], checks["tax_id_format"]["clearable"]) == (
        "fail",
        False,
    )

    r = await fpod.post(
        f"{FP}/onboardings/{ob_id}/resubmission",
        json={"reason": "The tax ID must be 9 digits; upload your signed W-9"},
    )
    assert r.status_code == 200, r.text
    again = r.json()
    assert (again["status"], again["documents"], again["checks"]) == ("invited", [], [])
    new_token = again["portal_url"].rsplit("/", 1)[-1]
    assert (await fpod.get(f"/api/v1/vendor-portal/{token}")).status_code == 404  # old link dead
    assert (await fpod.get(f"/api/v1/vendor-portal/{new_token}")).json()["status"] == "open"
