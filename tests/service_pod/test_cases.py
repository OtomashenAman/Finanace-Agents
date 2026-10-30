from typing import Any

from httpx import AsyncClient

from tests.conftest import ClientFactory, MakeUser
from tests.service_pod.conftest import act


async def _ok(r: Any) -> dict[str, Any]:
    assert r.status_code in (200, 201), r.text
    return r.json()  # type: ignore[no-any-return]


async def test_only_the_finance_admin_uses_the_pod(
    make_user: MakeUser, signed_in_client: ClientFactory, ar_case: dict[str, Any]
) -> None:
    user = await signed_in_client(await make_user("analyst@example.com"))
    for path in (
        "/api/v1/pod/workflows",
        "/api/v1/pod/cases",
        f"/api/v1/pod/cases/{ar_case['id']}",
        "/api/v1/pod/snapshots",
        "/api/v1/pod/ar/portfolio",
        "/api/v1/pod/tasks",
    ):
        assert (await user.get(path)).status_code == 403, path


async def test_coverage_is_checked(pod: AsyncClient, snapshot: dict[str, Any]) -> None:
    # FP&A needs GL and transactions this snapshot doesn't have: refused, nothing invented
    r = await pod.post(
        "/api/v1/pod/cases",
        json={"workflow": "fpa_trend", "snapshot_id": snapshot["id"], "title": "Q3"},
    )
    assert r.status_code == 422
    assert "gl lines" in r.json()["detail"]["message"]


async def test_approve_and_complete(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    assert ar_case["reference"].startswith("AR-")
    assert ar_case["status"] == "draft"
    assert ar_case["allowed_actions"]["approve"] is None
    assert ar_case["allowed_actions"]["complete"] is not None  # approve first

    case = await _ok(await act(pod, ar_case, "approve"))
    assert case["status"] == "approved"
    assert case["approvals"][0]["valid"] is True
    assert case["approvals"][0]["content_hash"] == case["fingerprint"]

    case = await _ok(await act(pod, case, "complete"))
    assert case["status"] == "completed"
    r = await act(pod, case, "add_review_task", kind="other", detail="late note")
    assert r.status_code == 409  # completed cases are locked


async def test_stale_version_is_refused(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    await _ok(await act(pod, ar_case, "edit", state={"note": "first"}))
    r = await act(pod, ar_case, "edit", state={"note": "second"})  # still version 1
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "stale_version"


async def test_open_review_tasks_block_approval(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    case = await _ok(
        await act(
            pod,
            ar_case,
            "add_review_task",
            kind="unknown_date",
            subject="INV-101",
            detail="First payment date not stated",
        )
    )
    r = await act(pod, case, "approve")
    assert r.status_code == 409
    assert "review task" in r.json()["detail"]["message"]

    task_id = case["review_tasks"][0]["id"]
    case = await _ok(
        await act(
            pod,
            case,
            "resolve_review_task",
            task_id=task_id,
            resolution="Customer confirmed Nov 12 by reply",
        )
    )
    assert case["review_tasks"][0]["resolved_by"] == "Fa"
    await _ok(await act(pod, case, "approve"))


async def test_change_after_approval_goes_back_to_draft(
    pod: AsyncClient, ar_case: dict[str, Any]
) -> None:
    case = await _ok(await act(pod, ar_case, "approve"))
    approved_hash = case["fingerprint"]

    case = await _ok(
        await act(
            pod, case, "add_review_task", kind="dispute", subject="INV-102", detail="$6k disputed"
        )
    )
    assert case["status"] == "draft"
    assert case["fingerprint"] != approved_hash
    assert case["approvals"][0]["valid"] is False


async def test_commitments(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    r = await act(pod, ar_case, "propose_commitment", invoice_id="I101", amount="16000")
    assert r.status_code == 422  # more than the open balance

    case = await _ok(
        await act(pod, ar_case, "propose_commitment", invoice_id="I101", amount="6000")
    )
    case = await _ok(
        await act(
            pod,
            case,
            "propose_commitment",
            invoice_id="I101",
            amount="9000",
            expected_date="2026-11-20",
        )
    )
    r = await act(pod, case, "propose_commitment", invoice_id="I101", amount="1")
    assert r.status_code == 422  # 6000 + 9000 already cover the balance

    r = await act(
        pod, case, "propose_commitment", invoice_id="I102", amount="100", probability="0.5"
    )
    assert r.status_code == 422  # a probability below 1 needs a reason

    undated, dated = case["commitments"]
    r = await act(pod, case, "decide_commitment", commitment_id=undated["id"], decision="approved")
    assert r.status_code == 409
    assert "without a date" in r.json()["detail"]["message"]

    case = await _ok(
        await act(pod, case, "decide_commitment", commitment_id=dated["id"], decision="approved")
    )
    assert [c["status"] for c in case["commitments"]] == ["proposed", "approved"]


async def test_review_queue(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    await _ok(
        await act(
            pod,
            ar_case,
            "add_review_task",
            kind="missing_document",
            subject="INV-101",
            detail="Customer asks for approved timesheets",
        )
    )
    queue = (await pod.get("/api/v1/pod/review-queue")).json()
    assert len(queue) == 1
    assert queue[0]["case_reference"] == ar_case["reference"]
    assert queue[0]["task"]["kind"] == "missing_document"
