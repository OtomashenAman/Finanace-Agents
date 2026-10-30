"""The Excel export and the sample workbooks (built here by scripts/pod_samples.py, the same
code that writes docs/sample-uploads/service-pod)."""

import io
import tempfile
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from scripts.pod_samples import main as build_samples

from src.app.entities.models import LegalEntity
from src.app.service_pod.core.workflows import Capacity, WorkflowKey
from tests.conftest import FakeLLM
from tests.service_pod.conftest import PodUser

ALL = list(WorkflowKey)

# The sample files, freshly built (docs/ isn't in the repository)
SAMPLES = Path(tempfile.mkdtemp(prefix="service-pod-samples-"))
build_samples(SAMPLES)


async def _upload(
    client: AsyncClient, entity: LegalEntity, name: str, data: bytes | None = None
) -> Any:
    body = data if data is not None else (SAMPLES / name).read_bytes()
    return await client.post(
        "/api/v1/pod/snapshots/workbook",
        files={
            "file": (
                name,
                body,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"entity_id": str(entity.id)},
    )


@pytest.fixture
async def users(pod_user: PodUser) -> dict[str, AsyncClient]:
    _, poster = await pod_user("fa@example.com", *[(w, Capacity.POSTER) for w in (ALL[0], ALL[1])])
    _, prep = await pod_user("prep@example.com", *[(w, Capacity.PREPARER) for w in ALL])
    _, rev = await pod_user("rev@example.com", *[(w, Capacity.REVIEWER) for w in ALL])
    return {"poster": poster, "prep": prep, "rev": rev}


async def test_sample_workbook_opens_every_workflow(
    users: dict[str, AsyncClient], entity: LegalEntity
) -> None:
    r = await _upload(users["poster"], entity, "service-pod.xlsx")
    assert r.status_code == 201, r.text
    snap = r.json()["snapshot"]
    assert len(snap["coverage"]) == 12
    assert snap["is_demo"] is True
    assert (
        await _upload(users["poster"], entity, "service-pod.xlsx")
    ).status_code == 200  # same content

    selections: dict[str, dict[str, Any]] = {
        "ar_collections": {"customer_id": "C1", "invoice_ids": ["I101", "I102"]},
        "bank_recon": {"receipt_reference": "WIRE-2901", "customer_id": "C1"},
    }
    for workflow in ALL:
        r = await users["prep"].post(
            "/api/v1/pod/cases",
            json={
                "workflow": workflow.value,
                "snapshot_id": snap["id"],
                "title": workflow.value,
                "selection": selections.get(workflow.value, {}),
            },
        )
        assert r.status_code == 201, (workflow, r.text)

    portfolio = (await users["rev"].get("/api/v1/pod/ar/portfolio")).json()
    assert [b["count"] for b in portfolio["aging"]] == [2, 2, 2, 0, 1]
    unapplied = (await users["rev"].get("/api/v1/pod/bank/unapplied")).json()
    assert unapplied["possible_duplicates"] == 1
    assert "CHK-1001" not in {r["reference"] for r in unapplied["rows"]}  # already recorded


async def test_broken_workbook_names_the_problem(
    users: dict[str, AsyncClient], entity: LegalEntity
) -> None:
    r = await _upload(users["poster"], entity, "service-pod-broken.xlsx")
    assert r.status_code == 422
    assert "unknown customer C9" in r.json()["detail"]["message"]

    wb = load_workbook(SAMPLES / "service-pod.xlsx")
    wb["Invoices"]["F3"] = "lots"  # Amount of the second invoice
    buf = io.BytesIO()
    wb.save(buf)
    r = await _upload(users["poster"], entity, "edited.xlsx", buf.getvalue())
    assert r.status_code == 422
    assert "Sheet 'Invoices' row 3, original_amount" in r.json()["detail"]["message"]

    wb = load_workbook(SAMPLES / "service-pod.xlsx")
    wb.create_sheet("Notes")
    buf = io.BytesIO()
    wb.save(buf)
    r = await _upload(users["poster"], entity, "notes.xlsx", buf.getvalue())
    assert "Unknown sheet 'Notes'" in r.json()["detail"]["message"]


async def test_bank_flow_with_the_sample_files(
    users: dict[str, AsyncClient], entity: LegalEntity, fake_llm: FakeLLM
) -> None:
    prep, rev, poster = users["prep"], users["rev"], users["poster"]
    snap = (await _upload(poster, entity, "service-pod.xlsx")).json()["snapshot"]
    case = (
        await prep.post(
            "/api/v1/pod/cases",
            json={
                "workflow": "bank_recon",
                "snapshot_id": snap["id"],
                "title": "WIRE-2901",
                "selection": {"receipt_reference": "WIRE-2901", "customer_id": "C1"},
            },
        )
    ).json()

    fake_llm.output = {"opening": "Dear Harbor AP,", "closing": "Thank you,"}
    draft = (
        await prep.post(
            f"/api/v1/pod/cases/{case['id']}/messages/compose",
            json={"purpose": "allocation_request"},
        )
    ).json()
    msg = (
        await prep.post(
            f"/api/v1/pod/cases/{case['id']}/messages",
            json={
                "audience": "customer",
                "purpose": "allocation_request",
                "to_email": draft["to_email"],
                "subject": draft["subject"],
                "body": draft["body"],
            },
        )
    ).json()
    url = f"/api/v1/pod/messages/{msg['id']}"
    checks = {"recipient": True, "mapping": True, "tone": True}
    msg = (
        await rev.post(
            f"{url}/approve", json={"expected_version": msg["version"], "checks": checks}
        )
    ).json()
    sent = (await prep.post(f"{url}/send", json={"expected_version": msg["version"]})).json()

    text = "Apply $6,000 to INV-101 and $3,000 to INV-102."
    fake_llm.output = {
        "allocations": [
            {
                "invoice_number": "INV-101",
                "amount": "6000",
                "quote": "Apply $6,000 to INV-101",
                "confidence": 0.95,
            },
            {
                "invoice_number": "INV-102",
                "amount": "3000",
                "quote": "$3,000 to INV-102",
                "confidence": 0.95,
            },
        ],
        "document_requests": [],
        "unclear": [],
    }
    await prep.post(
        f"/api/v1/pod/cases/{case['id']}/replies",
        json={"from_email": draft["to_email"], "body": text, "reply_to_message_id": sent["id"]},
    )

    async def act(client: AsyncClient, action: str, **payload: Any) -> dict[str, Any]:
        nonlocal case
        case = (await client.get(f"/api/v1/pod/cases/{case['id']}")).json()
        r = await client.post(
            f"/api/v1/pod/cases/{case['id']}/actions",
            json={"action": action, "expected_version": case["version"], "payload": payload},
        )
        assert r.status_code == 200, r.text
        case = r.json()
        return case

    await act(prep, "submit")
    await act(rev, "review", decision="approved")
    (task,) = (await act(prep, "create_posting_task"))["posting_tasks"]

    async def task_action(action: str, **body: Any) -> Any:
        nonlocal task
        r = await poster.post(
            f"/api/v1/pod/tasks/{task['id']}/actions",
            json={"action": action, "expected_version": task["version"], **body},
        )
        if r.status_code == 200:
            task = r.json()
        return r

    await task_action("approve")
    await task_action("record", external_txn_id="PMT-77")
    wrong = (await _upload(poster, entity, "service-pod-wrong-posting.xlsx")).json()["snapshot"]
    assert (await task_action("verify", snapshot_id=wrong["id"])).status_code == 409
    right = (await _upload(poster, entity, "service-pod-after-posting.xlsx")).json()["snapshot"]
    r = await task_action("verify", snapshot_id=right["id"])
    assert r.status_code == 200, r.text
    assert task["status"] == "verified"


def test_the_generator_matches_the_deck(tmp_path: Path) -> None:
    from scripts.pod_samples import ledger

    gl, _ = ledger()
    by = {(g["Period"], g["Account ID"]): g["Amount"] for g in gl}
    rev, cogs = by[("2026-09", "A400")], by[("2026-09", "A500")]
    opex = sum(by[("2026-09", a)] for a in ("A600", "A610", "A620"))
    assert (rev, cogs, opex, rev - cogs - opex) == (540000, 318000, 137000, 85000)  # slide 21
