"""Who gets into the Finance POD, capacity grants, and the wall between the two PODs."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.auth.models import User
from src.app.entities.models import LegalEntity
from src.app.service_pod.core.workflows import WorkflowKey
from tests.conftest import ClientFactory, MakeUser
from tests.finance_pod.conftest import Cap, GrantFn, PersonFn, open_demo
from tests.service_pod.conftest import open_ar_case


async def test_only_capacity_holders_get_in(
    admin: AsyncClient, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    outsider = await signed_in_client(await make_user("nobody@example.com"))
    assert (await outsider.get("/api/v1/finance/me")).status_code == 403
    assert (await outsider.get("/api/v1/finance/cases")).status_code == 403

    r = await admin.get("/api/v1/finance/me")
    assert r.status_code == 200
    assert r.json()["is_admin"] is True


async def test_admin_grants_and_revokes_a_capacity(
    admin: AsyncClient,
    admin_user: User,
    entity: LegalEntity,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    db: AsyncSession,
) -> None:
    user = await make_user("req@example.com")
    client = await signed_in_client(user)
    body = {"user_id": str(user.id), "capacity": "requester", "entity_id": str(entity.id)}

    r = await admin.post("/api/v1/finance/capacities", json=body)
    assert r.status_code == 201, r.text
    granted = r.json()
    assert granted["label"] == "Requester"
    assert granted["entity"]["code"] == "US01"
    assert granted["granted_by"] == admin_user.full_name
    assert (await admin.post("/api/v1/finance/capacities", json=body)).status_code == 409

    me = (await client.get("/api/v1/finance/me")).json()
    assert me["is_admin"] is False
    assert [(c["capacity"], [e["code"] for e in c["entities"]]) for c in me["capacities"]] == [
        ("requester", ["US01"])
    ]
    listed = (await admin.get("/api/v1/finance/capacities")).json()
    assert [a["user"]["email"] for a in listed] == ["req@example.com"]

    r = await admin.delete(f"/api/v1/finance/capacities/{granted['id']}")
    assert r.status_code == 204
    assert (await client.get("/api/v1/finance/me")).status_code == 403

    events = list(
        await db.scalars(
            select(AuditEvent.event_type)
            .where(AuditEvent.event_type.like("finance.capacity_%"))
            .order_by(AuditEvent.seq)
        )
    )
    assert events == ["finance.capacity_granted", "finance.capacity_revoked"]


async def test_only_admins_manage_capacities(person: PersonFn) -> None:
    user, client = await person("req@example.com", Cap.REQUESTER)
    assert (await client.get("/api/v1/finance/capacities")).status_code == 403
    r = await client.post(
        "/api/v1/finance/capacities", json={"user_id": str(user.id), "capacity": "controller"}
    )
    assert r.status_code == 403
    assert (await client.get("/api/v1/finance/capacities/catalog")).status_code == 200


async def test_an_all_entities_grant_covers_every_entity(
    admin: AsyncClient, make_user: MakeUser, grant: GrantFn
) -> None:
    user = await make_user("ctl@example.com")
    await grant(user, Cap.CONTROLLER)
    rows = (await admin.get("/api/v1/finance/capacities")).json()
    assert rows[0]["entity"] is None


async def test_the_two_pods_never_serve_each_others_cases(
    admin: AsyncClient, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    service_case = await open_ar_case(admin, snapshot)
    r = await open_demo(admin, snapshot)
    assert r.status_code == 201, r.text
    finance_case = r.json()

    assert (await admin.get(f"/api/v1/finance/cases/{service_case['id']}")).status_code == 404
    assert (await admin.get(f"/api/v1/pod/cases/{finance_case['id']}")).status_code == 404
    finance_ids = {c["id"] for c in (await admin.get("/api/v1/finance/cases")).json()}
    service_ids = {c["id"] for c in (await admin.get("/api/v1/pod/cases")).json()}
    assert finance_ids == {finance_case["id"]}
    assert finance_case["id"] not in service_ids

    r = await admin.post(
        "/api/v1/finance/cases",
        json={
            "workflow": WorkflowKey.AR_COLLECTIONS.value,
            "snapshot_id": snapshot["id"],
            "title": "x",
            "selection": {},
        },
    )
    assert r.status_code == 422
    finance_workflows = [w["key"] for w in (await admin.get("/api/v1/finance/workflows")).json()]
    assert finance_workflows == [
        demo_flow.key.value,
        "ap_purchase_request",
        "ap_vendor_onboarding",
        "ap_invoice_match",
        "ap_month_close",
        "ar_client_account",
        "ar_billing",
    ]
    service_workflows = [w["key"] for w in (await admin.get("/api/v1/pod/workflows")).json()]
    assert not set(service_workflows) & set(finance_workflows)
