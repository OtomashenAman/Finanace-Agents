"""Service POD fixtures. The figures are the deck's own examples (Harbor Distribution,
INV-101 / INV-102, WIRE-2901): test fixtures, never client accounting."""

import copy
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User, UserRole
from src.app.entities.models import EntityAssignment, LegalEntity
from src.app.service_pod.core.access.models import PodAssignment
from src.app.service_pod.core.workflows import Capacity, WorkflowKey
from tests.conftest import ClientFactory, MakeUser

AR = WorkflowKey.AR_COLLECTIONS
BANK = WorkflowKey.BANK_RECON
TRS = WorkflowKey.TREASURY

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


PodUser = Callable[..., Awaitable[tuple[User, AsyncClient]]]


@pytest.fixture
async def entity(db: AsyncSession) -> LegalEntity:
    e = LegalEntity(code="US01", name="US Operations")
    db.add(e)
    await db.commit()
    return e


@pytest.fixture
def pod_user(
    db: AsyncSession, make_user: MakeUser, signed_in_client: ClientFactory, entity: LegalEntity
) -> PodUser:
    """`await pod_user("x@example.com", (AR, Capacity.PREPARER), ...)` -> (user, client)."""

    async def _make(
        email: str, *roles: tuple[WorkflowKey, Capacity], role: UserRole = UserRole.USER
    ) -> tuple[User, AsyncClient]:
        user = await make_user(email, role)
        db.add(EntityAssignment(user_id=user.id, entity_id=entity.id))
        db.add_all(PodAssignment(user_id=user.id, workflow=w, capacity=c) for w, c in roles)
        await db.commit()
        return user, await signed_in_client(user)

    return _make


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
async def ar_team(pod_user: PodUser, entity: LegalEntity) -> dict[str, Any]:
    """An AR preparer, an AR reviewer, a Finance Admin poster and an imported snapshot."""
    poster, poster_client = await pod_user(
        "fa@example.com", (AR, Capacity.POSTER), (BANK, Capacity.POSTER)
    )
    prep, prep_client = await pod_user("ar.user@example.com", (AR, Capacity.PREPARER))
    rev, rev_client = await pod_user("ar.reviewer@example.com", (AR, Capacity.REVIEWER))
    r = await import_snapshot(poster_client, entity)
    assert r.status_code == 201, r.text
    return {
        "poster": poster_client,
        "prep": prep_client,
        "rev": rev_client,
        "users": {"poster": poster, "prep": prep, "rev": rev},
        "snapshot": r.json()["snapshot"],
    }


@pytest.fixture
async def ar_case(ar_team: dict[str, Any]) -> dict[str, Any]:
    r = await ar_team["prep"].post(
        "/api/v1/pod/cases",
        json={
            "workflow": "ar_collections",
            "snapshot_id": ar_team["snapshot"]["id"],
            "title": "Harbor Distribution",
            "selection": {"customer_id": "C1", "invoice_ids": ["I101", "I102"]},
        },
    )
    assert r.status_code == 201, r.text
    case: dict[str, Any] = r.json()
    return case
