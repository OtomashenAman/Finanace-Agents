"""Deleting a snapshot with everything that depends on it (admin): later snapshots, cases and
all their children, in an order the database accepts; the audit trail keeps the record."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.messaging.models import PodMessage
from src.app.service_pod.core.snapshots.models import PodSnapshot
from tests.conftest import FakeLLM
from tests.service_pod.conftest import act, customer_replies, import_snapshot
from tests.service_pod.fpa_data import fpa_document
from tests.service_pod.test_fpa import CORRECTION
from tests.service_pod.test_fpa import _open as fpa_open


async def _with_everything(
    pod: AsyncClient, snapshot: dict[str, Any], ar_case: dict[str, Any], llm: FakeLLM
) -> tuple[dict[str, Any], dict[str, Any]]:
    """An answered AR case (messages, a reply to them, a commitment citing the reply) and a
    bank statement snapshot built on the source, with a case of its own."""
    case = await customer_replies(pod, ar_case, llm)
    reply = next(m for m in case["messages"] if m["direction"] == "inbound")
    r = await act(
        pod,
        case,
        "propose_commitment",
        invoice_id="I101",
        amount="5000",
        expected_date="2026-11-20",
        source_message_id=reply["id"],
    )
    assert r.status_code == 200, r.text
    body = (
        "reference,payer,date,amount,currency,cleared\n"
        "WIRE-9,Harbor Distribution,2026-11-05,9000,USD,yes\n"
    )
    r = await pod.post(
        f"/api/v1/pod/snapshots/{snapshot['id']}/bank-statement",
        files={"file": ("s.csv", body.encode(), "text/csv")},
    )
    assert r.status_code == 201, r.text
    child = r.json()["snapshot"]
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "bank_recon",
            "snapshot_id": child["id"],
            "title": "WIRE-9",
            "selection": {"receipt_reference": "WIRE-9", "customer_id": "C1"},
        },
    )
    assert r.status_code == 201, r.text
    return child, r.json()


async def test_preview_then_delete_everything(
    pod: AsyncClient,
    snapshot: dict[str, Any],
    ar_case: dict[str, Any],
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    child, bank_case = await _with_everything(pod, snapshot, ar_case, fake_llm)

    # The plain delete still refuses a snapshot in use
    r = await pod.request(
        "DELETE", f"/api/v1/pod/snapshots/{snapshot['id']}", json={"reason": "wrong import"}
    )
    assert r.status_code == 409

    preview = (await pod.get(f"/api/v1/pod/snapshots/{snapshot['id']}/dependents")).json()
    assert {s["id"] for s in preview["snapshots"]} == {snapshot["id"], child["id"]}
    assert {c["reference"] for c in preview["cases"]} == {
        ar_case["reference"],
        bank_case["reference"],
    }
    assert preview["messages"] == 2 and preview["commitments"] == 1
    assert preview["evidence"] is False  # nothing approved, nothing verified

    url = f"/api/v1/pod/snapshots/{snapshot['id']}/purge"
    r = await pod.post(url, json={"reason": "test data", "confirm": "Someone Else"})
    assert r.status_code == 422  # the company name must be typed
    r = await pod.post(url, json={"reason": "test data", "confirm": "e-solutions inc"})
    assert r.status_code == 200, r.text

    for model in (PodSnapshot, PodCase, PodMessage):
        assert await db.scalar(select(func.count()).select_from(model)) == 0
    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "pod.snapshot_purged")
    )
    assert event is not None
    assert set(event.details["cases"]) == {ar_case["reference"], bank_case["reference"]}
    assert (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).status_code == 404


async def test_deleting_a_later_snapshot_keeps_the_parent(
    pod: AsyncClient, snapshot: dict[str, Any], ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    child, bank_case = await _with_everything(pod, snapshot, ar_case, fake_llm)
    r = await pod.post(
        f"/api/v1/pod/snapshots/{child['id']}/purge",
        json={"reason": "wrong statement", "confirm": child["company_name"]},
    )
    assert r.status_code == 200, r.text
    assert [c["reference"] for c in r.json()["cases"]] == [bank_case["reference"]]
    assert (await pod.get(f"/api/v1/pod/snapshots/{snapshot['id']}")).status_code == 200
    assert (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).status_code == 200


async def test_a_kept_case_loses_only_the_verifying_link(pod: AsyncClient, entity: Any) -> None:
    """An FP&A correction verified by a fresh snapshot: deleting that snapshot keeps the case
    and its verified posting, and says the verifying snapshot is gone."""
    source = (await import_snapshot(pod, entity, fpa_document())).json()["snapshot"]
    case = await fpa_open(pod, source)
    case = (await act(pod, case, "propose_correction", **CORRECTION)).json()
    case = (
        await act(
            pod, case, "set_commentary", highlights=[{"text": "Cloud overstated.", "fact_ids": []}]
        )
    ).json()
    case = (await act(pod, case, "approve")).json()
    case = (await act(pod, case, "queue_correction", correction_id="C1")).json()
    task = case["posting_tasks"][0]
    task = (
        await pod.post(
            f"/api/v1/pod/tasks/{task['id']}/actions",
            json={
                "action": "record",
                "expected_version": task["version"],
                "external_txn_id": "JE-900",
            },
        )
    ).json()
    fresh = fpa_document(source_reference="export after JE-900", as_of="2026-10-06")
    for g in fresh["gl_lines"]:
        if g["id"] in ("GL-A6200-2026-09", "GL-A6300-2026-09"):
            g["amount"] = "20000"
            g["transaction_ids"].append(f"JE-900:{1 if 'A6200' in g['id'] else 2}")
    for n, (account, amount) in enumerate((("A6200", "-3000"), ("A6300", "3000")), start=1):
        fresh["transactions"].append(
            {
                "id": f"JE-900:{n}",
                "date": "2026-09-30",
                "period": "2026-09",
                "type": "JournalEntry",
                "account_id": account,
                "amount": amount,
                "status": "Posted",
                "gl_line_id": f"GL-{account}-2026-09",
            }
        )
    snap = (await import_snapshot(pod, entity, fresh)).json()["snapshot"]
    r = await pod.post(
        f"/api/v1/pod/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": snap["id"]},
    )
    assert r.json()["status"] == "verified", r.text

    preview = (await pod.get(f"/api/v1/pod/snapshots/{snap['id']}/dependents")).json()
    assert preview["cases"] == [] and preview["verified_elsewhere"] == 1
    r = await pod.post(
        f"/api/v1/pod/snapshots/{snap['id']}/purge",
        json={"reason": "test export", "confirm": "E-Solutions Inc"},
    )
    assert r.status_code == 200, r.text
    kept = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    (posting,) = kept["posting_tasks"]
    assert posting["status"] == "verified"
    assert posting["verification_snapshot_id"] is None
    assert "deleted" in posting["verification"]["source_deleted"]


async def test_deleting_a_data_source_with_its_pod_data(
    pod: AsyncClient,
    admin_user: Any,
    entity: Any,
    db: AsyncSession,
    monkeypatch: Any,
) -> None:
    from src.app.service_pod.core.snapshots import service as snapshot_service
    from tests.service_pod.test_quickbooks_pnl import _import, _reports, _source

    async def fake_read(*_: Any) -> Any:
        return _reports()

    monkeypatch.setattr(snapshot_service, "_read_pnl", fake_read)
    source = await _source(db, admin_user)
    snap = (await _import(pod, source, entity)).json()["snapshot"]
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "fpa_trend",
            "snapshot_id": snap["id"],
            "title": "Aug-Sep",
            "selection": {"start": "2026-08", "end": "2026-09"},
        },
    )
    assert r.status_code == 201, r.text

    preview = (await pod.get(f"/api/v1/pod/snapshots/sources/{source.id}/dependents")).json()
    assert [s["id"] for s in preview["snapshots"]] == [snap["id"]]
    assert len(preview["cases"]) == 1

    r = await pod.delete(f"/api/v1/data-sources/{source.id}", params={"with_dependents": "true"})
    assert r.status_code == 204, r.text
    assert await db.scalar(select(func.count()).select_from(PodSnapshot)) == 0
    assert await db.scalar(select(func.count()).select_from(PodCase)) == 0
    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "pod.data_source_purged")
    )
    assert event is not None and len(event.details["cases"]) == 1


async def test_deleting_a_data_source_alone_keeps_the_snapshots(
    pod: AsyncClient, admin_user: Any, entity: Any, db: AsyncSession
) -> None:
    from tests.service_pod.test_quickbooks_pnl import _import, _source

    source = await _source(db, admin_user)
    snap = (await _import(pod, source, entity)).json()["snapshot"]
    r = await pod.delete(f"/api/v1/data-sources/{source.id}")
    assert r.status_code == 204, r.text
    assert (await pod.get(f"/api/v1/pod/snapshots/{snap['id']}")).status_code == 200


async def test_removing_a_users_pod_data_keeps_the_user(
    pod: AsyncClient,
    admin_user: Any,
    entity: Any,
    db: AsyncSession,
    make_user: Any,
    signed_in_client: Any,
) -> None:
    from src.app.auth.models import User, UserRole
    from src.app.data_sources.models import DataSource
    from tests.service_pod.conftest import open_ar_case
    from tests.service_pod.test_quickbooks_pnl import _source

    colleague = await make_user("colleague@example.com", UserRole.FINANCE_ADMIN)
    their = await signed_in_client(colleague)
    snap = (await import_snapshot(their, entity)).json()["snapshot"]
    case = await open_ar_case(their, snap)
    await _source(db, colleague)  # their QuickBooks connection

    preview = (await pod.get(f"/api/v1/pod/snapshots/users/{colleague.id}/data")).json()
    assert preview["user_name"] == colleague.full_name
    assert len(preview["data_sources"]) == 1
    assert [c["reference"] for c in preview["cases"]] == [case["reference"]]

    url = f"/api/v1/pod/snapshots/users/{colleague.id}/data/remove"
    assert (
        await pod.post(url, json={"reason": "left", "confirm": "nobody@x.com"})
    ).status_code == 422
    mine = f"/api/v1/pod/snapshots/users/{admin_user.id}/data/remove"
    assert (
        await pod.post(mine, json={"reason": "x", "confirm": admin_user.email})
    ).status_code in (409, 422)

    r = await pod.post(url, json={"reason": "left the team", "confirm": "colleague@example.com"})
    assert r.status_code == 200, r.text
    assert await db.scalar(select(func.count()).select_from(PodSnapshot)) == 0
    assert await db.scalar(select(func.count()).select_from(PodCase)) == 0
    assert await db.scalar(select(func.count()).select_from(DataSource)) == 0
    colleague_id = colleague.id
    db.expire_all()
    kept = await db.get(User, colleague_id)
    assert kept is not None and kept.is_active is False


async def test_hard_deleting_a_user_with_pod_records_is_refused_clearly(
    pod: AsyncClient, entity: Any, make_user: Any, signed_in_client: Any
) -> None:
    from src.app.auth.models import UserRole

    colleague = await make_user("colleague2@example.com", UserRole.FINANCE_ADMIN)
    their = await signed_in_client(colleague)
    assert (await import_snapshot(their, entity)).status_code == 201
    r = await pod.delete(f"/api/v1/users/{colleague.id}")
    assert r.status_code == 409  # was a 500: the snapshot still names them
    assert "Service POD" in r.json()["detail"]["message"]
