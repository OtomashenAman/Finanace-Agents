"""Taking a snapshot out of use: archive (kept as evidence, restorable) or, when nothing
depends on it, delete."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.entities.models import LegalEntity
from tests.service_pod.conftest import import_snapshot, snapshot_payload


async def _remove(client: Any, snapshot_id: str, how: str, reason: str = "wrong as-of date") -> Any:
    if how == "delete":
        return await client.request(
            "DELETE", f"/api/v1/pod/snapshots/{snapshot_id}", json={"reason": reason}
        )
    return await client.post(f"/api/v1/pod/snapshots/{snapshot_id}/{how}", json={"reason": reason})


async def test_archive_hides_and_restore_brings_back(
    pod: AsyncClient, snapshot: dict[str, Any], entity: LegalEntity
) -> None:
    wrong = (await import_snapshot(pod, entity, snapshot_payload(as_of="2000-02-02"))).json()
    sid = wrong["snapshot"]["id"]

    r = await _remove(pod, sid, "archive")
    assert r.status_code == 200, r.text
    assert r.json()["archived"] is True
    assert r.json()["archived_reason"] == "wrong as-of date"
    listed = [s["id"] for s in (await pod.get("/api/v1/pod/snapshots")).json()]
    assert sid not in listed
    everything = (await pod.get("/api/v1/pod/snapshots?include_archived=true")).json()
    assert sid in [s["id"] for s in everything]
    # The portfolio no longer picks it, even though it's the newest
    p = (await pod.get("/api/v1/pod/ar/portfolio")).json()
    assert p["snapshot"]["id"] == snapshot["id"]

    r = await pod.post(f"/api/v1/pod/snapshots/{sid}/restore")
    assert r.json()["archived"] is False
    assert sid in [s["id"] for s in (await pod.get("/api/v1/pod/snapshots")).json()]


async def test_only_unused_snapshots_can_be_deleted(
    pod: AsyncClient,
    snapshot: dict[str, Any],
    ar_case: dict[str, Any],
    entity: LegalEntity,
    db: AsyncSession,
) -> None:
    used = snapshot
    r = await _remove(pod, used["id"], "delete")
    assert r.status_code == 409
    assert "1 case(s) use it" in r.json()["detail"]["message"]

    # A bank statement builds on a snapshot: the parent can't go either
    child = await pod.post(
        f"/api/v1/pod/snapshots/{used['id']}/bank-statement",
        files={
            "file": (
                "s.csv",
                b"reference,payer,date,amount,currency,cleared\n"
                b"WIRE-1,Harbor,2026-11-05,10,USD,yes\n",
                "text/csv",
            )
        },
    )
    child_id = child.json()["snapshot"]["id"]

    wrong = (await import_snapshot(pod, entity, snapshot_payload(as_of="2000-02-02"))).json()
    sid = wrong["snapshot"]["id"]
    assert wrong["snapshot"]["in_use"] is None
    r = await _remove(pod, sid, "delete", "imported with the wrong date")
    assert r.status_code == 204, r.text
    assert (await pod.get(f"/api/v1/pod/snapshots/{sid}")).status_code == 404

    audit = (
        await db.execute(
            text(
                "SELECT details->>'reason' FROM audit_events "
                "WHERE event_type = 'pod.snapshot_deleted'"
            )
        )
    ).scalar_one()
    assert audit == "imported with the wrong date"

    # The same content can be imported again afterwards
    again = await import_snapshot(pod, entity, snapshot_payload(as_of="2000-02-02"))
    assert again.status_code == 201

    # Outside that one service path, the database still refuses
    with pytest.raises(DBAPIError, match="immutable"):
        await db.execute(text("DELETE FROM pod_snapshots WHERE id = :id"), {"id": child_id})
    await db.rollback()
