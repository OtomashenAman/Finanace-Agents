"""Bank-first manual posting (deck slide 44): recording a transaction ID is not verification;
only a later, different snapshot of the same books that contains the posting is."""

from typing import Any

from src.app.core.db import get_sessionmaker
from src.app.entities.models import LegalEntity
from src.app.service_pod.access.models import PodAssignment
from src.app.service_pod.workflows import Capacity, WorkflowKey
from tests.service_pod.conftest import act, import_snapshot, snapshot_payload

TASK = {
    "kind": "receive_payment",
    "reference": "WIRE-2901",
    "instructions": {
        "allocations": [
            {"invoice": "INV-101", "amount": "6000"},
            {"invoice": "INV-102", "amount": "3000"},
        ]
    },
}


async def _approved_case(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> dict[str, Any]:
    case = (await act(ar_team["prep"], ar_case, "submit")).json()
    return (await act(ar_team["rev"], case, "review", decision="approved")).json()  # type: ignore[no-any-return]


async def _task_action(client: Any, task: dict[str, Any], action: str, **body: Any) -> Any:
    return await client.post(
        f"/api/v1/pod/tasks/{task['id']}/actions",
        json={"action": action, "expected_version": task["version"], **body},
    )


async def test_posting_lifecycle(
    ar_team: dict[str, Any], ar_case: dict[str, Any], entity: LegalEntity
) -> None:
    prep, poster = ar_team["prep"], ar_team["poster"]
    url = f"/api/v1/pod/cases/{ar_case['id']}/tasks"
    assert (await prep.post(url, json=TASK)).status_code == 409  # case not approved yet

    case = await _approved_case(ar_team, ar_case)
    r = await prep.post(url, json=TASK)
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "proposed"
    assert (await prep.post(url, json=TASK)).status_code == 409  # same posting twice

    r = await _task_action(prep, task, "approve")
    assert r.status_code == 404  # preparers don't see the posting queue
    task = (await _task_action(poster, task, "approve")).json()
    r = await _task_action(poster, task, "record")
    assert r.status_code == 409  # needs the QuickBooks transaction ID
    task = (await _task_action(poster, task, "record", external_txn_id="PMT-77")).json()
    assert task["status"] == "recorded_unverified"

    case = (await prep.get(f"/api/v1/pod/cases/{case['id']}")).json()
    assert case["allowed_actions"]["complete"] is not None  # unverified posting blocks closing

    # The case's own snapshot proves nothing
    r = await _task_action(poster, task, "verify", snapshot_id=ar_team["snapshot"]["id"])
    assert r.status_code == 409
    assert "fresh export" in r.json()["detail"]["message"]

    # A fresh export without the payment
    fresh = snapshot_payload(source_reference="test export 2")
    sid = (await import_snapshot(poster, entity, fresh)).json()["snapshot"]["id"]
    r = await _task_action(poster, task, "verify", snapshot_id=sid)
    assert r.status_code == 409
    assert "PMT-77 isn't in the fresh snapshot" in r.json()["detail"]["message"]

    # A fresh export that contains it
    fresh = snapshot_payload(source_reference="test export 3")
    fresh["payments"] = [
        {
            "id": "PMT-77",
            "customer_id": "C1",
            "date": "2026-11-06",
            "amount": "9000",
            "currency": "USD",
            "reference": "WIRE-2901",
            "allocations": [
                {"invoice_id": "I101", "amount": "6000"},
                {"invoice_id": "I102", "amount": "3000"},
            ],
        }
    ]
    fresh["invoices"][0]["balance"] = "9000"
    fresh["invoices"][1]["balance"] = "7000"
    sid = (await import_snapshot(poster, entity, fresh)).json()["snapshot"]["id"]
    task = (await _task_action(poster, task, "verify", snapshot_id=sid)).json()
    assert task["status"] == "verified"
    assert task["verification"]["transaction"] == "PMT-77"

    case = (await prep.get(f"/api/v1/pod/cases/{case['id']}")).json()
    assert case["allowed_actions"]["complete"] is None
    assert (await act(prep, case, "complete")).json()["status"] == "completed"


async def test_proposer_cant_post_their_own_task(
    ar_team: dict[str, Any], ar_case: dict[str, Any]
) -> None:
    """A preparer who also holds posting rights still can't approve or record their task."""
    user = ar_team["users"]["prep"]
    async with get_sessionmaker()() as session:
        session.add(
            PodAssignment(
                user_id=user.id, workflow=WorkflowKey.BANK_RECON, capacity=Capacity.POSTER
            )
        )
        await session.commit()
    await _approved_case(ar_team, ar_case)
    task = (
        await ar_team["prep"].post(f"/api/v1/pod/cases/{ar_case['id']}/tasks", json=TASK)
    ).json()
    r = await _task_action(ar_team["prep"], task, "approve")
    assert r.status_code == 409
    assert "other than the proposer" in r.json()["detail"]["message"]
