from typing import Any

from httpx import AsyncClient

from src.app.entities.models import LegalEntity
from src.app.service_pod.core.workflows import Capacity, WorkflowKey
from tests.service_pod.conftest import AR, TRS, PodUser, act, import_snapshot

FPA = WorkflowKey.FPA_TREND


async def _ok(r: Any) -> dict[str, Any]:
    assert r.status_code in (200, 201), r.text
    return r.json()  # type: ignore[no-any-return]


async def test_case_needs_preparer_and_complete_source(ar_team: dict[str, Any]) -> None:
    snapshot_id = ar_team["snapshot"]["id"]
    body = {"workflow": "ar_collections", "snapshot_id": snapshot_id, "title": "x"}
    r = await ar_team["rev"].post("/api/v1/pod/cases", json=body)
    assert r.status_code == 403  # reviewers don't open cases

    # FP&A needs GL and transactions this snapshot doesn't have: refused, nothing invented
    body["workflow"] = "fpa_trend"
    r = await ar_team["prep"].post("/api/v1/pod/cases", json=body)
    assert r.status_code == 403  # not an FP&A preparer
    assert "FP&A" in r.json()["detail"]["message"]


async def test_coverage_is_checked(pod_user: PodUser, ar_team: dict[str, Any]) -> None:
    _, client = await pod_user("fpa@example.com", (FPA, Capacity.PREPARER))
    r = await client.post(
        "/api/v1/pod/cases",
        json={"workflow": "fpa_trend", "snapshot_id": ar_team["snapshot"]["id"], "title": "Q3"},
    )
    assert r.status_code == 422
    assert "gl lines" in r.json()["detail"]["message"]


async def test_maker_checker_flow(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> None:
    prep, rev = ar_team["prep"], ar_team["rev"]
    assert ar_case["reference"].startswith("AR-")
    assert ar_case["status"] == "draft"
    assert ar_case["allowed_actions"]["submit"] is None
    assert ar_case["allowed_actions"]["review"] is not None  # the preparer can't review

    case = await _ok(await act(prep, ar_case, "submit"))
    assert case["status"] == "in_review"

    r = await act(prep, case, "review", decision="approved")
    assert r.status_code == 409  # own case

    r = await act(rev, case, "review", decision="rejected")
    assert r.status_code == 422  # a reason is required

    case = await _ok(await act(rev, case, "review", decision="approved"))
    assert case["status"] == "approved"
    assert case["approvals"][0]["valid"] is True
    assert case["approvals"][0]["content_hash"] == case["fingerprint"]

    case = await _ok(await act(prep, case, "complete"))
    assert case["status"] == "completed"
    r = await act(prep, case, "add_review_task", kind="other", detail="late note")
    assert r.status_code == 409  # completed cases are locked


async def test_stale_version_is_refused(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> None:
    prep = ar_team["prep"]
    await _ok(await act(prep, ar_case, "edit", state={"note": "first"}))
    r = await act(prep, ar_case, "edit", state={"note": "second"})  # still version 1
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "stale_version"


async def test_open_review_tasks_block_approval(
    ar_team: dict[str, Any], ar_case: dict[str, Any]
) -> None:
    prep, rev = ar_team["prep"], ar_team["rev"]
    case = await _ok(
        await act(
            prep,
            ar_case,
            "add_review_task",
            kind="unknown_date",
            subject="INV-101",
            detail="First payment date not stated",
        )
    )
    r = await act(prep, case, "submit")
    assert r.status_code == 409
    assert "review task" in r.json()["detail"]["message"]

    task_id = case["review_tasks"][0]["id"]
    case = await _ok(
        await act(
            rev,
            case,
            "resolve_review_task",
            task_id=task_id,
            resolution="Customer confirmed Nov 12 by reply",
        )
    )
    assert case["review_tasks"][0]["resolved_by"] == "Ar Reviewer"
    await _ok(await act(prep, case, "submit"))


async def test_change_after_approval_reopens_review(
    ar_team: dict[str, Any], ar_case: dict[str, Any]
) -> None:
    prep, rev = ar_team["prep"], ar_team["rev"]
    case = await _ok(await act(prep, ar_case, "submit"))
    case = await _ok(await act(rev, case, "review", decision="approved"))
    approved_hash = case["fingerprint"]

    case = await _ok(
        await act(
            rev, case, "add_review_task", kind="dispute", subject="INV-102", detail="$6k disputed"
        )
    )
    assert case["status"] == "in_review"
    assert case["fingerprint"] != approved_hash
    assert case["approvals"][0]["valid"] is False


async def test_commitments(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> None:
    prep, rev = ar_team["prep"], ar_team["rev"]
    r = await act(prep, ar_case, "propose_commitment", invoice_id="I101", amount="16000")
    assert r.status_code == 422  # more than the open balance

    case = await _ok(
        await act(prep, ar_case, "propose_commitment", invoice_id="I101", amount="6000")
    )
    case = await _ok(
        await act(
            prep,
            case,
            "propose_commitment",
            invoice_id="I101",
            amount="9000",
            expected_date="2026-11-20",
        )
    )
    r = await act(prep, case, "propose_commitment", invoice_id="I101", amount="1")
    assert r.status_code == 422  # 6000 + 9000 already cover the balance

    r = await act(
        prep, case, "propose_commitment", invoice_id="I102", amount="100", probability="0.5"
    )
    assert r.status_code == 422  # a probability below 1 needs a reason

    undated, dated = case["commitments"]
    r = await act(prep, case, "decide_commitment", commitment_id=dated["id"], decision="approved")
    assert r.status_code == 409  # the preparer doesn't approve

    r = await act(rev, case, "decide_commitment", commitment_id=undated["id"], decision="approved")
    assert r.status_code == 409
    assert "without a date" in r.json()["detail"]["message"]

    case = await _ok(
        await act(rev, case, "decide_commitment", commitment_id=dated["id"], decision="approved")
    )
    assert [c["status"] for c in case["commitments"]] == ["proposed", "approved"]


async def test_cases_are_private_to_their_people(
    pod_user: PodUser, ar_team: dict[str, Any], ar_case: dict[str, Any]
) -> None:
    _, other_prep = await pod_user("other@example.com", (AR, Capacity.PREPARER))
    r = await other_prep.get(f"/api/v1/pod/cases/{ar_case['id']}")
    assert r.status_code == 404
    assert (await other_prep.get("/api/v1/pod/cases")).json() == []

    listed = (await ar_team["rev"].get("/api/v1/pod/cases")).json()
    assert [c["id"] for c in listed] == [ar_case["id"]]


async def test_treasury_needs_an_independent_cfo(pod_user: PodUser, entity: LegalEntity) -> None:
    _, poster = await pod_user("fa@example.com", (AR, Capacity.POSTER))
    snapshot = (await import_snapshot(poster, entity)).json()["snapshot"]
    _, analyst = await pod_user("analyst@example.com", (TRS, Capacity.PREPARER))
    _, head_and_cfo = await pod_user(
        "head@example.com", (TRS, Capacity.REVIEWER), (TRS, Capacity.FINAL_APPROVER)
    )
    _, cfo = await pod_user("cfo@example.com", (TRS, Capacity.FINAL_APPROVER))

    case = await _ok(
        await analyst.post(
            "/api/v1/pod/cases",
            json={"workflow": "treasury", "snapshot_id": snapshot["id"], "title": "13 weeks"},
        )
    )
    case = await _ok(await act(analyst, case, "submit"))
    case = await _ok(await act(head_and_cfo, case, "review", decision="approved"))
    assert case["status"] == "awaiting_final"

    r = await act(head_and_cfo, case, "final_review", decision="approved")
    assert r.status_code == 409
    assert "different person" in r.json()["detail"]["message"]

    case = await _ok(await act(cfo, case, "final_review", decision="approved"))
    assert case["status"] == "approved"
    assert [a["gate"] for a in case["approvals"]] == ["review", "final"]


async def test_review_queue(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> None:
    await _ok(
        await act(
            ar_team["prep"],
            ar_case,
            "add_review_task",
            kind="missing_document",
            subject="INV-101",
            detail="Customer asks for approved timesheets",
        )
    )
    client: AsyncClient = ar_team["rev"]
    queue = (await client.get("/api/v1/pod/review-queue")).json()
    assert len(queue) == 1
    assert queue[0]["case_reference"] == ar_case["reference"]
    assert queue[0]["task"]["kind"] == "missing_document"
