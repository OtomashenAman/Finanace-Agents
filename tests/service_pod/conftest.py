"""Service POD fixtures. The figures are the deck's own examples (Harbor Distribution,
INV-101 / INV-102, WIRE-2901): test fixtures, never client accounting."""

import copy
import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User, UserRole
from src.app.entities.models import LegalEntity
from tests.conftest import ClientFactory, FakeLLM, MakeUser

CUSTOMER_EMAIL = "ap@harbor.example"

BASE_SNAPSHOT: dict[str, Any] = {
    "provenance": "QUICKBOOKS_READONLY_EXPORT",
    "company_id": "QB-ESOL-1",
    "company_name": "E-Solutions Inc",
    "entity": "US01",
    "currency": "USD",
    "basis": "Accrual",
    "as_of": "2026-11-05",
    "source_reference": "test export 1",
    "customers": [
        {"id": "C1", "name": "Harbor Distribution", "email": CUSTOMER_EMAIL},
        {"id": "C2", "name": "Cobalt Systems", "email": "pay@cobalt.example"},
    ],
    "invoices": [
        {
            "id": "I101",
            "number": "INV-101",
            "customer_id": "C1",
            "txn_date": "2026-09-01",
            "due_date": "2026-10-01",
            "original_amount": "15000.00",
            "balance": "15000.00",
        },
        {
            "id": "I102",
            "number": "INV-102",
            "customer_id": "C1",
            "txn_date": "2026-09-05",
            "due_date": "2026-10-05",
            "original_amount": "10000.00",
            "balance": "10000.00",
        },
    ],
    "payments": [],
    "cash_position": {
        "as_of": "2026-11-05",
        "bank_balance": "250000",
        "quickbooks_cash_balance": "250000",
        "reconciliation_balance": "250000",
        "policy_buffer": "125000",
        "cleared": True,
    },
    "planned_outflows": [
        {
            "id": "O1",
            "date": "2026-11-20",
            "amount": "300000",
            "category": "Payroll",
            "approved": True,
        }
    ],
}


def snapshot_payload(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(BASE_SNAPSHOT)
    data.update(changes)
    return data


@pytest.fixture
async def entity(db: AsyncSession) -> LegalEntity:
    e = LegalEntity(code="US01", name="US Operations")
    db.add(e)
    await db.commit()
    return e


@pytest.fixture
async def admin_user(make_user: MakeUser) -> User:
    return await make_user("fa@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def pod(admin_user: User, signed_in_client: ClientFactory) -> AsyncClient:
    """The Finance Admin, who runs the Service POD alone."""
    return await signed_in_client(admin_user)


async def import_snapshot(
    client: AsyncClient, entity: LegalEntity, payload: dict[str, Any] | None = None
) -> Any:
    body = json.dumps(payload or snapshot_payload()).encode()
    return await client.post(
        "/api/v1/pod/snapshots/json",
        files={"file": ("export.json", body, "application/json")},
        data={"entity_id": str(entity.id)},
    )


async def act(client: AsyncClient, case: dict[str, Any], action: str, **payload: Any) -> Any:
    return await client.post(
        f"/api/v1/pod/cases/{case['id']}/actions",
        json={"action": action, "expected_version": case["version"], "payload": payload},
    )


@pytest.fixture
async def snapshot(pod: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(pod, entity)
    assert r.status_code == 201, r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    return snap


async def open_ar_case(
    pod: AsyncClient, snapshot: dict[str, Any], invoice_ids: tuple[str, ...] = ("I101", "I102")
) -> dict[str, Any]:
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "ar_collections",
            "snapshot_id": snapshot["id"],
            "title": "Harbor Distribution",
            "selection": {"customer_id": "C1", "invoice_ids": list(invoice_ids)},
        },
    )
    assert r.status_code == 201, r.text
    case: dict[str, Any] = r.json()
    return case


@pytest.fixture
async def ar_case(pod: AsyncClient, snapshot: dict[str, Any]) -> dict[str, Any]:
    return await open_ar_case(pod, snapshot)


async def customer_replies(
    pod: AsyncClient, case: dict[str, Any], llm: FakeLLM, text: str = "Noted, thank you."
) -> dict[str, Any]:
    """Mail the customer (outbox) and import their reply, read as saying nothing specific."""
    draft = (
        await pod.post(
            f"/api/v1/pod/cases/{case['id']}/messages",
            json={
                "audience": "customer",
                "purpose": "case_message",
                "to_email": CUSTOMER_EMAIL,
                "subject": "Your open invoices",
                "body": "Please confirm when you will pay.",
            },
        )
    ).json()
    sent = (
        await pod.post(
            f"/api/v1/pod/messages/{draft['id']}/send",
            json={
                "expected_version": draft["version"],
                "checks": {"recipient": True, "mapping": True, "tone": True},
            },
        )
    ).json()
    llm.output = {
        "intent": "reply",
        "tranches": [],
        "disputes": [],
        "document_requests": [],
        "unclear": [],
    }
    r = await pod.post(
        f"/api/v1/pod/cases/{case['id']}/replies",
        json={"from_email": CUSTOMER_EMAIL, "body": text, "reply_to_message_id": sent["id"]},
    )
    assert r.status_code == 201, r.text
    answered: dict[str, Any] = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    return answered


@pytest.fixture
async def answered_ar_case(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> dict[str, Any]:
    """An AR case the customer has answered, with nothing left to settle."""
    return await customer_replies(pod, ar_case, fake_llm)
