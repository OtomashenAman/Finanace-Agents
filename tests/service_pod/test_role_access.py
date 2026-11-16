"""Service POD roles: people work only in the workflows they're given, and prepare; signing
off stays with the Finance Admin."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from tests.conftest import DEFAULT_PASSWORD, ClientFactory, FakeLLM
from tests.service_pod.conftest import CUSTOMER_EMAIL, act, customer_replies

USERS = "/api/v1/users"
POD = "/api/v1/pod"


@pytest.fixture
def person(pod: AsyncClient, signed_in_client: ClientFactory, db: AsyncSession) -> Any:
    """`await person(role, **body)`: create someone through user management (as the admin)
    and sign them in."""

    async def _make(role: str, **body: Any) -> tuple[dict[str, Any], AsyncClient]:
        email = f"{role}@example.com"
        r = await pod.post(
            USERS,
            json={
                "email": email,
                "full_name": role,
                "password": DEFAULT_PASSWORD,
                "role": role,
                **body,
            },
        )
        assert r.status_code == 201, r.text
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        return r.json(), await signed_in_client(user)

    return _make


async def test_each_role_starts_with_its_workflows(pod: AsyncClient) -> None:
    expected = {
        "ar_specialist": ["ar_collections"],
        "accountant": ["bank_recon"],
        "treasury_analyst": ["treasury"],
        "fpa_analyst": ["fpa_trend"],
        "controller": ["ar_collections", "bank_recon", "reporting"],
        "user": [],
    }
    for role, workflows in expected.items():
        r = await pod.post(
            USERS,
            json={
                "email": f"{role}@example.com",
                "full_name": role,
                "password": DEFAULT_PASSWORD,
                "role": role,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["pod_workflows"] == workflows, role
    # The admin has every workflow
    me = (await pod.get("/api/v1/auth/me")).json()
    assert me["pod_workflows"] == [
        "ar_collections",
        "bank_recon",
        "fpa_trend",
        "treasury",
        "reporting",
    ]


async def test_the_admin_can_adjust_workflows(pod: AsyncClient, person: Any) -> None:
    created, client = await person("accountant", pod_workflows=["bank_recon", "treasury"])
    assert created["pod_workflows"] == ["bank_recon", "treasury"]
    keys = [w["key"] for w in (await client.get(f"{POD}/workflows")).json()]
    assert keys == ["bank_recon", "treasury"]

    r = await pod.patch(f"{USERS}/{created['id']}", json={"pod_workflows": ["treasury"]})
    assert r.json()["pod_workflows"] == ["treasury"]
    # A role change without a list resets to the new role's defaults
    r = await pod.patch(f"{USERS}/{created['id']}", json={"role": "fpa_analyst"})
    assert r.json()["pod_workflows"] == ["fpa_trend"]


async def test_no_workflow_no_service_pod(pod: AsyncClient, person: Any) -> None:
    _, client = await person("user")
    assert (await client.get(f"{POD}/cases")).status_code == 403


async def test_people_see_only_their_workflows(
    pod: AsyncClient,
    person: Any,
    ar_case: dict[str, Any],
) -> None:
    _, accountant = await person("accountant")
    _, ar = await person("ar_specialist")

    # Not their workflow: the case doesn't exist for them, lists leave it out
    assert (await accountant.get(f"{POD}/cases/{ar_case['id']}")).status_code == 404
    assert (await accountant.get(f"{POD}/cases")).json() == []
    assert (await accountant.get(f"{POD}/ar/portfolio")).status_code == 403
    dash = (await accountant.get(f"{POD}/dashboard")).json()
    assert dash["open_cases"] == 0
    r = await accountant.post(
        f"{POD}/cases/{ar_case['id']}/messages",
        json={
            "audience": "customer",
            "purpose": "case_message",
            "to_email": CUSTOMER_EMAIL,
            "subject": "Hi",
            "body": "Hello",
        },
    )
    assert r.status_code == 404

    # Their workflow: they see and work it
    assert (await ar.get(f"{POD}/cases/{ar_case['id']}")).status_code == 200
    assert [c["id"] for c in (await ar.get(f"{POD}/cases")).json()] == [ar_case["id"]]
    assert (await ar.get(f"{POD}/ar/portfolio")).status_code == 200


async def test_preparers_cannot_sign_off(
    pod: AsyncClient,
    person: Any,
    snapshot: dict[str, Any],
) -> None:
    _, ar = await person("ar_specialist")
    # They open a case and draft an email
    r = await ar.post(
        f"{POD}/cases",
        json={
            "workflow": "ar_collections",
            "snapshot_id": snapshot["id"],
            "title": "Harbor",
            "selection": {"customer_id": "C1", "invoice_ids": ["I101"]},
        },
    )
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["allowed_actions"]["approve"] == "Only a Finance Admin can sign off."
    assert case["allowed_actions"]["edit"] is None
    # ...but can't open a case in a workflow they don't have
    r = await ar.post(
        f"{POD}/cases",
        json={"workflow": "bank_recon", "snapshot_id": snapshot["id"], "title": "x"},
    )
    assert r.status_code == 403

    msg = (
        await ar.post(
            f"{POD}/cases/{case['id']}/messages",
            json={
                "audience": "customer",
                "purpose": "case_message",
                "to_email": CUSTOMER_EMAIL,
                "subject": "Payment schedule",
                "body": "Please confirm when INV-101 will be paid.",
            },
        )
    ).json()
    assert "id" in msg, msg

    # Signing off is the admin's
    assert (await act(ar, case, "approve")).status_code == 403
    assert (await act(ar, case, "cancel", reason="no")).status_code == 403
    r = await ar.post(
        f"{POD}/messages/{msg['id']}/send",
        json={
            "expected_version": msg["version"],
            "checks": {"recipient": True, "mapping": True, "tone": True},
        },
    )
    assert r.status_code == 403
    assert (await ar.post(f"{POD}/snapshots/{snapshot['id']}/archive")).status_code == 403

    # The admin still sees the preparer's case and can act on it
    assert (await pod.get(f"{POD}/cases/{case['id']}")).json()["allowed_actions"]["approve"] != (
        "Only a Finance Admin can sign off."
    )


async def test_ai_activity_shows_only_their_workflows(
    pod: AsyncClient, person: Any, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    await customer_replies(pod, ar_case, fake_llm)  # AI activity on an AR case
    admin_feed = (await pod.get(f"{POD}/dashboard")).json()["ai_activity"]
    assert admin_feed["recent"]

    _, accountant = await person("accountant")
    _, ar = await person("ar_specialist")
    assert (await accountant.get(f"{POD}/dashboard")).json()["ai_activity"]["recent"] == []
    ar_feed = (await ar.get(f"{POD}/dashboard")).json()["ai_activity"]
    assert ar_feed == admin_feed


async def test_books_status_reports_the_latest_source(
    pod: AsyncClient, snapshot: dict[str, Any]
) -> None:
    books = (await pod.get(f"{POD}/dashboard")).json()["books"]
    assert books["snapshots"] == 1
    assert books["latest_as_of"] == snapshot["as_of"]
    assert books["quickbooks_connected"] == 0

    r = await pod.post(f"{POD}/snapshots/{snapshot['id']}/archive", json={"reason": "wrong date"})
    assert r.status_code == 200, r.text
    books = (await pod.get(f"{POD}/dashboard")).json()["books"]
    assert books["snapshots"] == 0 and books["latest_as_of"] is None
