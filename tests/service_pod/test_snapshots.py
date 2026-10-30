from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import get_settings
from src.app.entities.models import LegalEntity
from tests.service_pod.conftest import import_snapshot, snapshot_payload


async def test_import_is_immutable_and_deduplicated(
    pod: AsyncClient, snapshot: dict[str, Any], entity: LegalEntity, db: AsyncSession
) -> None:
    first = snapshot
    assert first["coverage"] == [
        "customers",
        "invoices",
        "payments",
        "planned_outflows",
        "cash_position",
    ]
    assert first["row_counts"]["invoices"] == 2
    assert first["is_demo"] is False

    # Same content in another key order / number format: same snapshot, not a new one
    payload = snapshot_payload()
    payload["invoices"][0]["balance"] = "15000"
    again = await import_snapshot(pod, entity, dict(reversed(payload.items())))
    assert again.status_code == 200
    assert again.json()["snapshot"]["id"] == first["id"]

    with pytest.raises(DBAPIError, match="immutable"):
        await db.execute(text("UPDATE pod_snapshots SET company_name = 'x'"))
    await db.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        await db.execute(text("DELETE FROM pod_snapshots"))
    await db.rollback()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"entity": "UK01"}, "not US01"),
        ({"currency": "usd"}, "currency"),
        ({"extra_field": 1}, "extra_field"),
    ],
)
async def test_contract_violations_are_refused(
    pod: AsyncClient, entity: LegalEntity, change: dict[str, Any], message: str
) -> None:
    r = await import_snapshot(pod, entity, snapshot_payload(**change))
    assert r.status_code == 422
    assert message in r.json()["detail"]["message"]


async def test_broken_links_are_refused(pod: AsyncClient, entity: LegalEntity) -> None:
    payload = snapshot_payload()
    payload["invoices"][0]["customer_id"] = "C9"
    r = await import_snapshot(pod, entity, payload)
    assert r.status_code == 422
    assert "unknown customer C9" in r.json()["detail"]["message"]

    gl = snapshot_payload(
        accounts=[{"id": "A1", "name": "Revenue", "classification": "Income"}],
        gl_lines=[
            {
                "id": "G1",
                "account_id": "A1",
                "period": "2026-09",
                "amount": "100",
                "report_id": "PL-9",
                "transaction_ids": [],
            }
        ],
        transactions=[
            {
                "id": "T1",
                "date": "2026-09-03",
                "period": "2026-09",
                "type": "Invoice",
                "account_id": "A1",
                "amount": "100",
                "status": "Posted",
                "gl_line_id": "G1",
            }
        ],
    )
    r = await import_snapshot(pod, entity, gl)
    assert r.status_code == 422
    assert "doesn't cite it" in r.json()["detail"]["message"]


async def test_demo_data_can_be_switched_off(
    pod: AsyncClient, entity: LegalEntity, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = snapshot_payload(provenance="SYNTHETIC_DEMO", source_reference="deck fixture")
    monkeypatch.setattr(get_settings(), "pod_allow_demo_snapshots", False)
    r = await import_snapshot(pod, entity, demo)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "demo_snapshot_not_allowed"

    monkeypatch.setattr(get_settings(), "pod_allow_demo_snapshots", True)
    r = await import_snapshot(pod, entity, demo)
    assert r.status_code == 201
    assert r.json()["snapshot"]["is_demo"] is True


def _csv(*rows: str) -> dict[str, Any]:
    body = "reference,payer,date,amount,currency,cleared\n" + "\n".join(rows) + "\n"
    return {"file": ("statement.csv", body.encode(), "text/csv")}


async def test_bank_statement_makes_a_new_snapshot(
    pod: AsyncClient, snapshot: dict[str, Any]
) -> None:
    parent = snapshot
    url = f"/api/v1/pod/snapshots/{parent['id']}/bank-statement"
    r = await pod.post(url, files=_csv("WIRE-2901,Harbor Distribution,2026-11-05,9000,USD,yes"))
    assert r.status_code == 201, r.text
    child = r.json()["snapshot"]
    assert child["parent_id"] == parent["id"]
    assert child["source_type"] == "bank_csv"
    assert "bank_receipts" in child["coverage"]

    still = await pod.get(f"/api/v1/pod/snapshots/{parent['id']}")
    assert "bank_receipts" not in still.json()["coverage"]

    # A later statement can't silently change a receipt already recorded
    url = f"/api/v1/pod/snapshots/{child['id']}/bank-statement"
    r = await pod.post(url, files=_csv("WIRE-2901,Harbor Distribution,2026-11-05,9500,USD,yes"))
    assert r.status_code == 422
    r = await pod.post(url, files=_csv("WIRE-3000,Harbor,2026-11-06,10,EUR,yes"))
    assert r.status_code == 422
    assert "EUR" in r.json()["detail"]["message"]


async def test_rows(pod: AsyncClient, snapshot: dict[str, Any]) -> None:
    sid = snapshot["id"]
    r = await pod.get(f"/api/v1/pod/snapshots/{sid}/rows?collection=invoices")
    assert r.status_code == 200
    assert [i["number"] for i in r.json()["rows"]] == ["INV-101", "INV-102"]
