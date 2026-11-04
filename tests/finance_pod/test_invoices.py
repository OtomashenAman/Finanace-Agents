"""AP Phase 3: posting agent (duplicate guard), match agent (tolerances), exception agent
and the buyer's decisions, receipt agent and the receiver's mobile confirmation."""

import re
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.mail import FpEmail, MailKind
from tests.conftest import FakeLLM
from tests.finance_pod.test_procurement import approved

FP = "/api/v1/finance-pod"
TODAY = utcnow().date().isoformat()


async def issued_po(fpod: AsyncClient, other_admin: AsyncClient) -> dict[str, Any]:
    """PO for 10 boxes of pipette tips at the 42.50 contract price, issued to V-LAB."""
    pr = await approved(fpod, other_admin)
    await fpod.post(
        f"{FP}/requests/{pr['id']}/sourcing/choose",
        json={"contract_vendor_code": "V-LAB", "payment_terms": "Net 30"},
    )
    po = (await fpod.post(f"{FP}/requests/{pr['id']}/po")).json()
    for action in ("confirm", "issue"):
        fresh = (await fpod.get(f"{FP}/purchase-orders/{po['id']}")).json()
        r = await fpod.post(
            f"{FP}/purchase-orders/{po['id']}/{action}", json={"expected_version": fresh["version"]}
        )
        assert r.status_code == 200, r.text
    return r.json()


async def receive(fpod: AsyncClient, po: dict[str, Any], qty: str = "10") -> None:
    r = await fpod.post(
        f"{FP}/purchase-orders/{po['id']}/receipts",
        json={"received_on": TODAY, "lines": [{"po_line": 1, "quantity": qty}]},
    )
    assert r.status_code == 201, r.text


async def invoice(
    fpod: AsyncClient,
    po: dict[str, Any],
    number: str = "LS-1001",
    price: str = "42.50",
    qty: str = "10",
) -> dict[str, Any]:
    total = f"{float(price) * float(qty):.2f}"
    r = await fpod.post(
        f"{FP}/invoices",
        json={
            "vendor_code": "V-LAB",
            "vendor_invoice_number": number,
            "invoice_date": TODAY,
            "currency": "USD",
            "total": total,
            "po_reference": po["reference"],
            "lines": [
                {"description": "Pipette tips 200ul sterile", "quantity": qty, "unit_price": price}
            ],
        },
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    r = await fpod.post(
        f"{FP}/invoices/{inv['id']}/post", json={"expected_version": inv["version"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_a_clean_invoice_is_posted_matched_and_released_to_coding(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    po = await issued_po(fpod, other_admin)
    await receive(fpod, po)
    inv = await invoice(fpod, po)
    assert (inv["status"], inv["first_pass_matched"], inv["erp_system"]) == ("ready", True, "local")
    assert inv["match"]["outcome"] == "matched"
    assert inv["match"]["lines"][0]["po_line"] == 1
    assert inv["released_at"] is not None
    # The PO lists the invoices billed against it
    on_po = (await fpod.get(f"{FP}/invoices", params={"po_id": po["id"]})).json()
    assert [i["reference"] for i in on_po] == [inv["reference"]]


async def test_the_duplicate_guard_blocks_and_explains_and_a_person_can_release(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    po = await issued_po(fpod, other_admin)
    await receive(fpod, po)
    await invoice(fpod, po, number="LS-1001")
    dup = await invoice(fpod, po, number="ls 01001")  # same number, typed differently
    assert dup["status"] == "duplicate"
    assert dup["duplicate"]["hits"][0]["strength"] == "exact"
    assert "same vendor and invoice number" in dup["duplicate"]["explanation"]
    m = (await fpod.get(f"{FP}/measures/invoices")).json()
    assert m["duplicates_stopped"] == 1

    r = await fpod.post(
        f"{FP}/invoices/{dup['id']}/not-duplicate",
        json={
            "expected_version": dup["version"],
            "note": "Vendor confirmed it's a second delivery",
        },
    )
    released = r.json()
    assert released["status"] == "exception"  # posted; but only 10 received and 10 invoiced
    assert released["exception"]["kinds"] == ["quantity"]
    assert released["duplicate"]["overridden_by"]


async def test_a_price_variance_is_credited_and_the_invoice_released(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    po = await issued_po(fpod, other_admin)
    await receive(fpod, po)
    inv = await invoice(fpod, po, price="45.00")  # tolerance max(2% = 0.85, 1.00) = 1.00
    assert (inv["status"], inv["first_pass_matched"]) == ("exception", False)
    exc = inv["exception"]
    assert (exc["status"], exc["kinds"]) == ("open", ["price"])
    assert exc["issues"][0]["amount"] == "25.00"  # 2.50 over x 10
    assert "credit note for 25.00" in exc["vendor_query_body"]
    # The PO is untouched by the agents
    po_now = (await fpod.get(f"{FP}/purchase-orders/{po['id']}")).json()
    assert po_now["lines"][0]["unit_price"] == "42.50"

    r = await fpod.post(
        f"{FP}/invoice-exceptions/{exc['id']}/decide",
        json={"decision": "credit", "note": "Contract price applies"},
    )
    assert r.json()["exception"]["status"] == "waiting_vendor"
    assert await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.VENDOR_QUERY))
    r = await fpod.post(
        f"{FP}/invoice-exceptions/{exc['id']}/credit-note",
        json={"amount": "25.00", "reference": "CN-77"},
    )
    done = r.json()
    assert (done["status"], done["exception"]["status"]) == ("ready", "resolved")
    m = (await fpod.get(f"{FP}/measures/invoices")).json()
    assert (m["first_pass_judged"], m["first_pass_matched"]) == (1, 0)


async def test_only_the_buyers_amendment_changes_a_po_price_and_it_is_recorded(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    po = await issued_po(fpod, other_admin)
    await receive(fpod, po)
    inv = await invoice(fpod, po, price="45.00")
    r = await fpod.post(
        f"{FP}/invoice-exceptions/{inv['exception']['id']}/decide",
        json={
            "decision": "amend_po",
            "note": "New price list from November",
            "amendments": [{"po_line": 1, "unit_price": "45.00", "quantity": "10"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"
    po_now = (await fpod.get(f"{FP}/purchase-orders/{po['id']}")).json()
    assert (po_now["lines"][0]["unit_price"], po_now["lines"][0]["price_source"]) == (
        "45.00",
        "buyer",
    )
    audit = await fpod.get("/api/v1/audit-events", params={"category": "finance_pod"})
    assert any(
        "Buyer amended" in e["summary"] and "42.50 -> 10 x 45.00" in e["summary"]
        for e in audit.json()["items"]
    )


async def test_a_missing_receipt_is_chased_and_confirmed_on_the_receivers_phone(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    po = await issued_po(fpod, other_admin)
    inv = await invoice(fpod, po)  # nothing received yet
    exc = inv["exception"]
    assert (inv["status"], exc["status"], exc["kinds"]) == (
        "exception",
        "waiting_receipt",
        ["no_receipt"],
    )
    r = await fpod.post(
        f"{FP}/invoice-exceptions/{exc['id']}/decide",
        json={"decision": "accept", "note": "Looks fine"},
    )
    assert r.status_code == 422  # can't accept paying for what nobody confirmed received

    [req] = inv["receipt_requests"]
    assert req["receiver_email"] == "buyer@gia.example"  # the requester
    mail = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.RECEIPT_REQUEST))
    token = re.search(r"/receipt/(\S+)", mail.body).group(1)  # type: ignore[union-attr]
    view = (await fpod.get(f"/api/v1/receipt-confirm/{token}")).json()
    assert (view["status"], view["lines"][0]["ordered"]) == ("open", "10.0000")

    r = await fpod.post(
        f"/api/v1/receipt-confirm/{token}",
        json={"received_on": TODAY, "lines": [{"po_line": 1, "quantity": "10"}]},
    )
    assert r.status_code == 204, r.text
    after = (await fpod.get(f"{FP}/invoices/{inv['id']}")).json()
    assert (after["status"], after["exception"]["status"]) == ("ready", "resolved")
    assert (await fpod.get(f"/api/v1/receipt-confirm/{token}")).status_code == 404  # single use


async def test_the_capture_agent_reads_an_invoice_and_finds_vendor_and_po(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, fake_llm: FakeLLM
) -> None:
    po = await issued_po(fpod, other_admin)
    text = (
        f"Lab Supply Co  Tax ID 12-3456789\nINVOICE LS-2002  Date {TODAY}\n"
        f"Your PO: {po['reference']}\nPipette tips 200ul  10 x 42.50 = 425.00\nTotal 425.00"
    )
    read = {
        "vendor_name": "Lab Supply Co.",
        "vendor_tax_id": "12-3456789",
        "invoice_number": "LS-2002",
        "invoice_date": TODAY,
        "due_date": None,
        "po_number": po["reference"],
        "currency": "USD",
        "tax_total": "0",
        "total": "425.00",
        "lines": [
            {
                "description": "Pipette tips 200ul",
                "quantity": "10",
                "unit_price": "42.50",
                "amount": "425.00",
            }
        ],
    }
    fake_llm.output = read
    r = await fpod.post(
        f"{FP}/invoices/capture", files={"file": ("ls-2002.txt", text.encode(), "text/plain")}
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert (inv["vendor_code"], inv["po_id"], inv["total"]) == ("V-LAB", po["id"], "425.00")
    assert inv["extraction"]["verified"] is True

    fake_llm.output = {**read, "total": "999.00"}  # not in the text: not used
    r = await fpod.post(
        f"{FP}/invoices/capture", files={"file": ("again.txt", text.encode() + b" ", "text/plain")}
    )
    assert "isn't in the invoice's text" in r.json()["extraction"]["error"]
    assert r.json()["total"] is None


async def test_invoices_can_be_deleted_to_run_a_demo_again(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    po = await issued_po(fpod, other_admin)
    waiting = await invoice(fpod, po)  # no receipt: exception + receipt request
    await receive(fpod, po)
    clean = await invoice(fpod, po, number="LS-2000")
    mail = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.RECEIPT_REQUEST))
    token = re.search(r"/receipt/(\S+)", mail.body).group(1)  # type: ignore[union-attr]

    r = await fpod.post(f"{FP}/invoices/delete", json={"ids": [waiting["id"], clean["id"]]})
    assert r.json() == {"deleted": 2}
    assert (await fpod.get(f"{FP}/invoices")).json() == []
    assert (await fpod.get(f"{FP}/invoice-exceptions")).json() == []
    assert (await fpod.get(f"/api/v1/receipt-confirm/{token}")).status_code == 404  # cancelled
    # The delivery stays on the PO; the audit trail keeps the record
    assert len((await fpod.get(f"{FP}/purchase-orders/{po['id']}/receipts")).json()) == 1
    audit = await fpod.get("/api/v1/audit-events", params={"category": "finance_pod"})
    assert sum("Deleted INV-" in e["summary"] for e in audit.json()["items"]) == 2

    # The same invoice can be captured and matched again
    again = await invoice(fpod, po, number="LS-1001")
    assert again["status"] == "ready"
    r = await fpod.delete(f"{FP}/invoices/{again['id']}")
    assert r.status_code == 204


async def test_a_partial_delivery_is_billed_and_nothing_beyond_the_po_is(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    po = await issued_po(fpod, other_admin)  # 10 boxes ordered
    await receive(fpod, po, qty="4")
    part = await invoice(fpod, po, number="LS-P1", qty="4")
    assert part["status"] == "ready"  # 4 arrived, 4 billed: a valid partial invoice
    assert part["match"]["lines"][0]["ordered_left"] == "10.0000"

    # Receiving more than ordered is refused: the buyer amends the PO first
    r = await fpod.post(
        f"{FP}/purchase-orders/{po['id']}/receipts",
        json={"received_on": TODAY, "lines": [{"po_line": 1, "quantity": "7"}]},
    )
    assert r.status_code == 422
    assert "11 of 10 ordered" in r.json()["detail"]["message"]

    await receive(fpod, po, qty="6")  # the rest arrives: 10 of 10
    over = await invoice(fpod, po, number="LS-P2", qty="8")  # 4 billed already, 6 left
    assert over["status"] == "exception"
    assert any("has only 6.0000 left to bill" in i["message"] for i in over["exception"]["issues"])


async def test_the_match_agent_explains_with_the_quantity_trail_and_cited_figures(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, fake_llm: FakeLLM
) -> None:
    po = await issued_po(fpod, other_admin)  # 10 ordered
    await receive(fpod, po, qty="4")
    inv = await invoice(fpod, po, qty="4")
    [trail] = inv["match"]["trail"]
    assert (
        trail["ordered"],
        trail["received"],
        trail["billed_before"],
        trail["this_invoice"],
        trail["left_to_bill"],
    ) == ("10", "4", "0", "4", "6")

    fake_llm.output = {
        "highlights": [
            {
                "text": "The PO ordered this many and only part has arrived.",
                "fact_ids": ["l1.ordered", "l1.received"],
            },
            {
                "text": "This invoice bills exactly what arrived, so it matches.",
                "fact_ids": ["l1.this", "outcome"],
            },
            {"text": "The rest can be billed once it is delivered.", "fact_ids": ["l1.left"]},
        ]
    }
    r = await fpod.post(f"{FP}/invoices/{inv['id']}/explain")
    exp = r.json()["match"]["explanation"]
    assert exp["highlights"][0]["fact_ids"] == ["l1.ordered", "l1.received"]
    facts = {f["id"]: f["value"] for f in exp["facts"]}
    assert (facts["l1.ordered"], facts["l1.left"]) == ("10", "6")

    # A sentence stating its own figure is refused; the trail still shows the numbers
    fake_llm.output = {
        "highlights": [{"text": "The PO ordered 10 boxes.", "fact_ids": ["l1.ordered"]}]
    }
    r = await fpod.post(f"{FP}/invoices/{inv['id']}/explain")
    assert "states a number" in r.json()["match"]["explanation_error"]
    assert r.json()["match"]["trail"][0]["left_to_bill"] == "6"
