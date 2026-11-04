"""Payments and vendor support: the payment agent's run and risk checks, the analyst's
call-back, treasury's dual release, the vendor agent's remittances and answers."""

from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.data_sources import crypto
from src.app.finance_pod.mail import FpEmail, MailKind
from src.app.finance_pod.onboarding.models import (
    FpOnboarding,
    FpVendorBankAccount,
    OnboardingKind,
    OnboardingStatus,
)
from tests.conftest import FakeLLM
from tests.finance_pod.test_invoices import invoice, receive
from tests.finance_pod.test_procurement import approved

FP = "/api/v1/finance-pod"


async def bank_account(db: AsyncSession, vendor: str = "V-LAB", days_ago: int = 90) -> None:
    """A verified account on file (normally from onboarding's portal, call-back, approver)."""
    admin = await db.scalar(select(User).limit(1))
    assert admin is not None
    ob = FpOnboarding(
        kind=OnboardingKind.BANK_CHANGE,
        status=OnboardingStatus.ACTIVE,
        vendor_name="Lab Supply Co",
        vendor_email="orders@labsupply.example",
        vendor_code=vendor,
        invited_by=admin.id,
    )
    db.add(ob)
    await db.flush()
    db.add(
        FpVendorBankAccount(
            vendor_code=vendor,
            onboarding_id=ob.id,
            bank_name="First Bank",
            account_name="Lab Supply Co",
            routing_number_enc=crypto.encrypt("021000021"),
            account_number_enc=crypto.encrypt("555000111"),
            account_last4="0111",
            created_at=utcnow() - timedelta(days=days_ago),
        )
    )
    await db.commit()


async def ready_invoice(fpod: AsyncClient, other_admin: AsyncClient, terms: str = "Net 30") -> Any:
    """An approved invoice dated today, due in 30 days: the runs look 30 days ahead."""
    r = await fpod.put(
        f"{FP}/settings",
        json={
            "currency": "USD",
            "purchasing_threshold": "10000",
            "min_quotes": 3,
            "allow_self_approval": False,
            "payment_horizon_days": 30,
        },
    )
    assert r.status_code == 200, r.text
    pr = await approved(fpod, other_admin)
    await fpod.post(
        f"{FP}/requests/{pr['id']}/sourcing/choose",
        json={"contract_vendor_code": "V-LAB", "payment_terms": terms},
    )
    po = (await fpod.post(f"{FP}/requests/{pr['id']}/po")).json()
    for action in ("confirm", "issue"):
        fresh = (await fpod.get(f"{FP}/purchase-orders/{po['id']}")).json()
        await fpod.post(
            f"{FP}/purchase-orders/{po['id']}/{action}", json={"expected_version": fresh["version"]}
        )
    po = (await fpod.get(f"{FP}/purchase-orders/{po['id']}")).json()
    await receive(fpod, po)
    inv = await invoice(fpod, po)
    assert inv["status"] == "ready"
    return inv


async def release(client: AsyncClient, run: dict[str, Any], note: str = "") -> Any:
    fresh = (await client.get(f"{FP}/payment-runs/{run['id']}")).json()
    return await client.post(
        f"{FP}/payment-runs/{run['id']}/approve",
        json={"expected_version": fresh["version"], "note": note},
    )


async def test_the_agent_proposes_two_people_release_and_the_vendor_agent_remits(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    assert (await fpod.post(f"{FP}/payment-runs")).status_code == 422  # nothing to pay yet
    await bank_account(db)
    inv = await ready_invoice(fpod, other_admin)
    r = await fpod.post(f"{FP}/payment-runs")
    assert r.status_code == 201, r.text
    run = r.json()
    [item] = run["items"]
    assert (item["amount"], item["reason"], item["callback_status"]) == (
        "425.00",
        "due",
        "not_needed",
    )
    assert [f["key"] for f in item["flags"]] == ["first_payment"]
    assert run["groups"][0]["key"] == "USD · First Bank"
    assert (await fpod.get(f"{FP}/invoices/{inv['id']}")).json()["status"] == "ready"  # not paid

    r = await release(fpod, run, "Within budget")
    assert r.json()["status"] == "partly_approved"
    assert (await release(fpod, run)).status_code == 403  # the same person can't release twice
    r = await release(other_admin, run)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "released"
    assert done["items"][0]["payment_ref"] == f"{run['reference']}-001"
    paid = (await fpod.get(f"{FP}/invoices/{inv['id']}")).json()
    assert (paid["status"], paid["payment_ref"]) == ("paid", f"{run['reference']}-001")
    remit = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.REMITTANCE))
    assert remit is not None and "account ending 0111" in remit.body
    csv = (await fpod.get(f"{FP}/payment-runs/{run['id']}/bank-file")).text
    assert "555000111" in csv and "425.00" in csv
    m = (await fpod.get(f"{FP}/measures/payments")).json()
    assert (m["payments"], m["on_time"]) == (1, 1)


async def test_deleting_a_released_run_puts_its_invoices_back_to_pay_again(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    await bank_account(db)
    inv = await ready_invoice(fpod, other_admin)
    run = (await fpod.post(f"{FP}/payment-runs")).json()
    await release(fpod, run)
    assert (await release(other_admin, run)).json()["status"] == "released"
    # A paid invoice is the payment record: it can't be deleted while the run exists
    assert (await fpod.delete(f"{FP}/invoices/{inv['id']}")).status_code == 409

    r = await fpod.post(f"{FP}/payment-runs/delete", json={"ids": [run["id"]]})
    assert r.json() == {"deleted": 1}
    back = (await fpod.get(f"{FP}/invoices/{inv['id']}")).json()
    assert (back["status"], back["payment_ref"], back["paid_at"]) == ("ready", None, None)
    assert (await fpod.get(f"{FP}/payment-runs/{run['id']}")).status_code == 404
    again = await fpod.post(f"{FP}/payment-runs")  # the demo runs again
    assert again.status_code == 201 and again.json()["items"][0]["invoice_id"] == inv["id"]


async def test_changed_bank_details_need_the_analysts_call_back_before_release(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    await bank_account(db, days_ago=3)
    await ready_invoice(fpod, other_admin)
    run = (await fpod.post(f"{FP}/payment-runs")).json()
    item = run["items"][0]
    assert item["callback_status"] == "needed"
    assert "call-back" in run["release_blockers"][0]
    r = await release(fpod, run)
    assert r.status_code == 422

    call = {
        "phone": "+1 555 0100",
        "source": "vendor master / earlier records",
        "contact": "Jo, accounts",
        "confirmed_last4": "9999",
    }
    url = f"{FP}/payment-runs/{run['id']}/items/{item['id']}/callback"
    r = await fpod.post(url, json={**call, "expected_version": run["version"]})
    assert r.status_code == 422  # not the account on file: don't pay
    r = await fpod.post(
        url, json={**call, "confirmed_last4": "0111", "expected_version": run["version"]}
    )
    assert r.json()["items"][0]["callback_status"] == "confirmed"
    assert (await release(fpod, r.json())).json()["status"] == "partly_approved"


async def test_an_early_pay_discount_is_taken_when_the_terms_allow(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None, db: AsyncSession
) -> None:
    await bank_account(db)
    await ready_invoice(fpod, other_admin, terms="2/10 Net 30")
    run = (await fpod.post(f"{FP}/payment-runs")).json()
    [item] = run["items"]
    assert (item["reason"], item["discount"], item["amount"]) == ("discount", "8.50", "416.50")
    assert run["discounts"] == "8.50"


async def test_the_vendor_agent_answers_status_questions_and_escalates_disputes(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    reference: None,
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    await ready_invoice(fpod, other_admin)  # LS-1001, approved, not yet paid
    fake_llm.output = {"intent": "status", "invoice_number": "LS-1001"}
    r = await fpod.post(
        "/api/v1/vendor-help",
        json={"from_email": "orders@labsupply.example", "question": "When will LS-1001 be paid?"},
    )
    assert r.status_code == 202
    answer = await db.scalar(select(FpEmail).where(FpEmail.kind == MailKind.QUERY_ANSWER))
    assert answer is not None and answer.to_email == "orders@labsupply.example"
    assert "LS-1001 is approved for payment" in answer.body

    # A stranger's email gets the same page reply, but no answer: an analyst checks
    fake_llm.output = {"intent": "status", "invoice_number": "LS-1001"}
    await fpod.post(
        "/api/v1/vendor-help",
        json={"from_email": "someone@else.example", "question": "When will LS-1001 be paid?"},
    )
    fake_llm.output = {"intent": "dispute", "invoice_number": None}
    await fpod.post(
        "/api/v1/vendor-help",
        json={
            "from_email": "orders@labsupply.example",
            "question": "You short-paid us last month.",
        },
    )
    queries = (await fpod.get(f"{FP}/vendor-queries")).json()
    assert [(q["intent"], q["status"]) for q in queries] == [
        ("dispute", "escalated"),
        ("status", "escalated"),
        ("status", "answered"),
    ]
    r = await fpod.post(
        f"{FP}/vendor-queries/{queries[0]['id']}/reply",
        json={"answer": "We deducted the credit note CN-77; details attached."},
    )
    assert r.json()["status"] == "resolved"
    m = (await fpod.get(f"{FP}/measures/payments")).json()
    assert (m["queries"], m["queries_answered_by_agent"], m["queries_open"]) == (3, 1, 1)
