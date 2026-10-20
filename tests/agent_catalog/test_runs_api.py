from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ap_invoice.models import ApInvoiceRun
from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.runs.models import AgentRun
from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from src.app.core.config import get_settings
from src.app.core.llm.base import LLMError
from tests.common.test_text_extraction import make_pdf
from tests.conftest import ClientFactory, FakeLLM, MakeUser

RUNS = "/api/v1/agents/ap_invoice/runs"
SUMMARY = "/api/v1/overview/summary"
PDF_EXAMPLE: dict[str, Any] = {
    "supplier": "Acme Cloud Services",
    "invoice_number": "INV-2048",
    "legal_entity": "US Operations",
    "invoice_total": "12500.00",
    "po_authorized_amount": "12500.00",
    "received_amount": "1000.00",
    "tax_total": None,
    "proposed_gl_account": None,
}

pytestmark = pytest.mark.usefixtures("synced_agents")


async def assign(
    db: AsyncSession, user: User, capacity: AgentCapacity, key: str = "ap_invoice"
) -> None:
    agent = await db.scalar(select(Agent).where(Agent.key == key))
    assert agent is not None
    db.add(AgentAssignment(user_id=user.id, agent_id=agent.id, capacity=capacity))
    await db.commit()


@pytest.fixture
async def preparer(make_user: MakeUser, db: AsyncSession) -> User:
    user = await make_user("ap.analyst@example.com", UserRole.USER)
    await assign(db, user, AgentCapacity.PREPARER)
    return user


@pytest.fixture
async def reviewer(make_user: MakeUser) -> User:
    """Only Finance Admins approve runs."""
    return await make_user("ap.approver@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def prep(preparer: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(preparer)


@pytest.fixture
async def rev(reviewer: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(reviewer)


async def new_run(client: AsyncClient, values: dict[str, Any] | None = None) -> dict[str, Any]:
    r = await client.post(RUNS)
    assert r.status_code == 201, r.text
    run: dict[str, Any] = r.json()
    if values is not None:
        r = await client.put(f"{RUNS}/{run['id']}/input", json={"values": values})
        assert r.status_code == 200, r.text
        run = r.json()
    return run


async def act(client: AsyncClient, run: dict[str, Any], action: str, **json: Any) -> dict[str, Any]:
    r = await client.post(f"{RUNS}/{run['id']}/{action}", json=json or None)
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    return result


async def analyzed_run(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    run = await new_run(client, {**PDF_EXAMPLE, **overrides})
    return await act(client, run, "analyze")


# --- form + catalog -----------------------------------------------------------------------


async def test_form_spec_describes_the_ap_invoice_fields(prep: AsyncClient) -> None:
    r = await prep.get("/api/v1/agents/ap_invoice/form")
    assert r.status_code == 200
    body = r.json()
    assert [(f["name"], f["kind"], f["required"]) for f in body["fields"]] == [
        ("supplier", "text", True),
        ("invoice_number", "text", True),
        ("legal_entity", "text", True),
        ("invoice_total", "money", True),
        ("po_authorized_amount", "money", True),
        ("received_amount", "money", True),
        ("tax_total", "money", False),
        ("proposed_gl_account", "text", False),
    ]
    assert body["controls"][0] == "Duplicate supplier/invoice"


async def test_catalog_reports_which_agents_have_a_workspace(
    admin: User, signed_in_client: ClientFactory
) -> None:
    c = await signed_in_client(admin)
    agents = {a["key"]: a["has_workspace"] for a in (await c.get("/api/v1/agents")).json()}
    assert agents["ap_invoice"] is True
    assert agents["expense_audit"] is False


async def test_agent_without_workspace_cannot_start_runs(
    preparer: User, prep: AsyncClient, db: AsyncSession
) -> None:
    await assign(db, preparer, AgentCapacity.PREPARER, key="expense_audit")
    r = await prep.post("/api/v1/agents/expense_audit/runs")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "workspace_unavailable"


# --- full maker-checker flow ----------------------------------------------------------------


async def test_full_flow_input_result_review(
    prep: AsyncClient,
    rev: AsyncClient,
    fake_llm: FakeLLM,
    db: AsyncSession,
    admin: User,
    signed_in_client: ClientFactory,
) -> None:
    # Input
    run = await new_run(prep, PDF_EXAMPLE)
    assert run["status"] == "draft"
    assert run["reference"].startswith("RUN-")
    assert run["business_reference"] == "INV-2048"
    assert run["input"]["invoice_total"] == "12500.00"
    assert run["permissions"]["can_analyze"] is True

    # Result
    run = await act(prep, run, "analyze")
    assert run["status"] == "analyzed"
    assert run["status_label"] == "Needs human review"
    assert run["headline"] == "Invoice discrepancy"
    assert run["priority"] == "high"
    assert [(f["code"], f["severity"]) for f in run["flags"]] == [
        ("DUPLICATE_CHECK_CLEAR", "pass"),
        ("PO_MATCH", "pass"),
        ("RECEIPT_MISMATCH", "high"),
        ("MISSING_GL", "warning"),
        ("MISSING_EVIDENCE", "warning"),
    ]
    calc = {c["key"]: c["value"] for c in run["calculations"]}
    assert calc["invoice_vs_receipt"] == "11500.00"
    narrative = run["narrative"]
    assert narrative["status"] == "ok"
    assert narrative["model"] == "fake-model"
    assert narrative["output"]["missing_evidence"] == ["Goods receipt note"]
    assert narrative["guard_warnings"] == []

    # The engine's values are stored typed in the agent's own table
    detail = await db.get(ApInvoiceRun, run["id"])
    assert detail is not None
    assert detail.invoice_vs_receipt == Decimal("11500.00")

    # The LLM saw only validated input and engine output
    system, user_payload = fake_llm.calls[0]
    assert "Never calculate, round or change any amount" in system
    assert '"invoice_vs_receipt"' in user_payload

    # Submit
    run = await act(prep, run, "submit")
    assert run["status"] == "pending_approval"
    assert len(run["result_hash"]) == 64
    locked = await prep.put(f"{RUNS}/{run['id']}/input", json={"values": PDF_EXAMPLE})
    assert locked.status_code == 409

    # Overview reflects the open run
    admin_client = await signed_in_client(admin)
    kpis = (await admin_client.get(SUMMARY)).json()
    assert kpis["kpis"]["pending_review"] == 1
    assert kpis["kpis"]["high_priority"] == 1
    assert kpis["kpis"]["runs_this_month"] == 1
    assert kpis["worklist"][0]["reference"] == "INV-2048"
    assert kpis["worklist"][0]["status_label"] == "Pending approval"

    # Review
    seen_by_reviewer = (await rev.get(f"{RUNS}/{run['id']}")).json()
    assert seen_by_reviewer["permissions"]["can_review"] is True
    assert seen_by_reviewer["permissions"]["can_edit"] is False
    run = await act(
        rev, run, "reviews", decision="approved", comment="Receipt confirmed with warehouse"
    )
    assert run["status"] == "approved"
    assert run["decided_at"] is not None
    assert run["reviews"][0]["reviewer"]["full_name"] == "Ap Approver"
    assert run["reviews"][0]["result_hash"] == run["result_hash"]

    after = (await admin_client.get(SUMMARY)).json()["kpis"]
    assert (after["pending_review"], after["high_priority"]) == (0, 0)

    events = list(await db.scalars(select(AuditEvent.event_type).order_by(AuditEvent.created_at)))
    run_events = [e for e in events if e.startswith("run.")]
    assert run_events == ["run.created", "run.analyzed", "run.submitted", "run.approved"]


async def test_changes_requested_reopens_the_run(
    prep: AsyncClient, rev: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await act(prep, await analyzed_run(prep), "submit")
    run = await act(rev, run, "reviews", decision="changes_requested", comment="Attach the receipt")
    assert run["status"] == "changes_requested"
    assert run["permissions"]["can_edit"] is False  # reviewer's view

    mine = (await prep.get(f"{RUNS}/{run['id']}")).json()
    assert mine["permissions"]["can_edit"] is True
    edited = await prep.put(
        f"{RUNS}/{run['id']}/input", json={"values": {**PDF_EXAMPLE, "received_amount": "12500.00"}}
    )
    assert edited.json()["status"] == "draft"  # previous analysis cleared

    run = await act(prep, edited.json(), "analyze")
    run = await act(prep, run, "submit")
    run = await act(rev, run, "reviews", decision="approved", comment="Now matches")
    assert run["status"] == "approved"
    assert [r["decision"] for r in run["reviews"]] == ["changes_requested", "approved"]


# --- validation -----------------------------------------------------------------------------


async def test_missing_required_fields_fail_validation(
    prep: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await new_run(prep, {"supplier": "Acme Cloud Services"})
    run = await act(prep, run, "analyze")

    assert run["status"] == "validation_failed"
    assert run["status_label"] == "Validation failed"
    failed_fields = {e["field"] for e in run["validation_errors"]}
    assert failed_fields == {
        "invoice_number",
        "legal_entity",
        "invoice_total",
        "po_authorized_amount",
        "received_amount",
    }
    assert run["flags"] == []
    assert fake_llm.calls == []  # nothing sent to the LLM


async def test_draft_still_rejects_invalid_values(prep: AsyncClient) -> None:
    run = await new_run(prep)
    r = await prep.put(f"{RUNS}/{run['id']}/input", json={"values": {"invoice_total": "-5"}})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-1] == "invoice_total"


async def test_duplicate_invoice_is_flagged(prep: AsyncClient, fake_llm: FakeLLM) -> None:
    first = await analyzed_run(prep)
    second = await analyzed_run(prep, supplier="ACME CLOUD SERVICES", invoice_number="inv-2048")

    assert second["headline"] == "Duplicate invoice suspected"
    duplicate = next(f for f in second["flags"] if f["code"] == "DUPLICATE_INVOICE")
    assert duplicate["severity"] == "high"
    assert first["reference"] in duplicate["message"]


# --- permissions ----------------------------------------------------------------------------


async def test_users_cannot_review_runs(prep: AsyncClient, fake_llm: FakeLLM) -> None:
    run = await act(prep, await analyzed_run(prep), "submit")
    assert run["permissions"]["can_review"] is False
    r = await prep.post(
        f"{RUNS}/{run['id']}/reviews", json={"decision": "approved", "comment": "ok!"}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["message"] == "Only a Finance Admin can approve runs."


async def test_users_only_see_their_own_runs(
    make_user: MakeUser,
    db: AsyncSession,
    prep: AsyncClient,
    admin: User,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    mine = await act(prep, await analyzed_run(prep), "submit")
    admins = await act(
        a := await signed_in_client(admin), await analyzed_run(a, invoice_number="ADM-1"), "submit"
    )

    other = await make_user("other.analyst@example.com", UserRole.USER)
    await assign(db, other, AgentCapacity.PREPARER)
    c = await signed_in_client(other)
    assert (await c.get(RUNS)).json() == []
    for run in (mine, admins):
        assert (await c.get(f"{RUNS}/{run['id']}")).status_code == 404
        r = await c.post(
            f"{RUNS}/{run['id']}/reviews", json={"decision": "approved", "comment": "ok!"}
        )
        assert r.status_code in (403, 404)
        assert (
            await c.put(f"{RUNS}/{run['id']}/input", json={"values": PDF_EXAMPLE})
        ).status_code == 404

    # The preparer doesn't see the admin's run either, and their overview counts only their own
    assert [r["id"] for r in (await prep.get(RUNS)).json()] == [mine["id"]]
    assert (await prep.get(SUMMARY)).json()["kpis"]["pending_review"] == 1
    assert (await a.get(SUMMARY)).json()["kpis"]["pending_review"] == 2


async def test_unassigned_user_cannot_see_runs(
    make_user: MakeUser, prep: AsyncClient, signed_in_client: ClientFactory
) -> None:
    run = await new_run(prep)
    outsider = await signed_in_client(await make_user("x@example.com", UserRole.USER))
    assert (await outsider.get(RUNS)).status_code == 404
    assert (await outsider.get(f"{RUNS}/{run['id']}")).status_code == 404


async def test_admin_can_view_prepare_and_review_without_assignment(
    admin: User, prep: AsyncClient, signed_in_client: ClientFactory, fake_llm: FakeLLM
) -> None:
    users_run = await act(prep, await analyzed_run(prep), "submit")
    c = await signed_in_client(admin)
    runs = (await c.get(RUNS)).json()
    assert runs[0]["business_reference"] == "INV-2048"
    assert (await c.get(f"{RUNS}/{users_run['id']}")).json()["permissions"]["can_review"] is True

    run = await act(c, await analyzed_run(c, invoice_number="INV-9001"), "submit")
    assert run["permissions"]["can_review"] is True


async def test_admin_may_approve_own_run_and_it_is_audited(
    admin: User, signed_in_client: ClientFactory, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    c = await signed_in_client(admin)
    run = await act(c, await analyzed_run(c), "submit")
    run = await act(c, run, "reviews", decision="approved", comment="Checked myself.")
    assert run["status"] == "approved"

    event = await db.scalar(select(AuditEvent).where(AuditEvent.event_type == "run.approved"))
    assert event is not None
    assert event.details["self_review"] is True


async def test_only_drafts_can_be_deleted(
    prep: AsyncClient, fake_llm: FakeLLM, db: AsyncSession
) -> None:
    draft = await new_run(prep)
    assert (await prep.delete(f"{RUNS}/{draft['id']}")).status_code == 204
    assert await db.get(AgentRun, draft["id"]) is None

    run = await analyzed_run(prep)
    assert (await prep.delete(f"{RUNS}/{run['id']}")).status_code == 409


# --- documents ------------------------------------------------------------------------------


async def upload(client: AsyncClient, run: dict[str, Any], name: str, data: bytes) -> Any:
    return await client.post(f"{RUNS}/{run['id']}/documents", files={"file": (name, data)})


async def test_upload_stores_only_extracted_text(prep: AsyncClient, fake_llm: FakeLLM) -> None:
    run = await new_run(prep, PDF_EXAMPLE)
    r = await upload(prep, run, "invoice.pdf", make_pdf(["Invoice INV-2048 total 12500.00"]))
    assert r.status_code == 201, r.text
    document = r.json()["documents"][0]
    assert document["extractor"] == "pdf"
    assert document["page_count"] == 1
    assert len(document["sha256"]) == 64
    assert "INV-2048" in document["text_preview"]

    full = (await prep.get(f"{RUNS}/{run['id']}/documents/{document['id']}")).json()
    assert "Invoice INV-2048 total 12500.00" in full["extracted_text"]

    # Evidence now exists, and the LLM receives the document text with an id to cite
    run = await act(prep, r.json(), "analyze")
    assert "MISSING_EVIDENCE" not in {f["code"] for f in run["flags"]}
    assert '"id": "D1"' in fake_llm.calls[-1][1]


async def test_upload_rules(
    prep: AsyncClient, fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await new_run(prep, PDF_EXAMPLE)
    pdf = make_pdf(["Invoice INV-2048 total 12500.00"])
    assert (await upload(prep, run, "a.pdf", pdf)).status_code == 201

    duplicate = await upload(prep, run, "copy.pdf", pdf)
    assert duplicate.status_code == 409
    assert "already attached as 'a.pdf'" in duplicate.json()["detail"]["message"]

    image = await upload(prep, run, "scan.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    assert image.status_code == 422
    assert image.json()["detail"]["code"] == "document_rejected"

    monkeypatch.setattr(get_settings(), "upload_max_bytes", 10)
    too_big = await upload(prep, run, "b.csv", b"supplier,total\nAcme,1\n")
    assert too_big.status_code == 413


async def test_changing_evidence_after_analysis_resets_it(
    prep: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await new_run(prep, PDF_EXAMPLE)
    run = (await upload(prep, run, "remit.csv", b"supplier,total\nAcme,12500.00\n")).json()
    run = await act(prep, run, "analyze")
    assert run["status"] == "analyzed"

    document_id = run["documents"][0]["id"]
    r = await prep.delete(f"{RUNS}/{run['id']}/documents/{document_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "draft"
    assert r.json()["flags"] == []


# --- LLM degradation ------------------------------------------------------------------------


async def test_llm_failure_does_not_block_the_run(prep: AsyncClient, fake_llm: FakeLLM) -> None:
    fake_llm.error = LLMError("Provider returned HTTP 503")
    run = await analyzed_run(prep)

    assert run["status"] == "analyzed"
    assert run["narrative"]["status"] == "failed"
    assert run["narrative"]["error"] == "Provider returned HTTP 503"
    assert run["permissions"]["can_submit"] is True


async def test_without_llm_config_narrative_is_not_configured(prep: AsyncClient) -> None:
    run = await analyzed_run(prep)  # no fake_llm: LLM_PROVIDER=none in tests
    assert run["narrative"]["status"] == "not_configured"


async def test_guard_flags_invented_figures(prep: AsyncClient, fake_llm: FakeLLM) -> None:
    fake_llm.output["key_points"] = ["Tax of 1,250.00 should be checked"]
    run = await analyzed_run(prep)
    assert run["narrative"]["guard_warnings"] == ["Figure not found in the source data: 1,250.00"]


async def test_llm_can_only_cite_fields_of_this_run(prep: AsyncClient, fake_llm: FakeLLM) -> None:
    await analyzed_run(prep)
    schema = fake_llm.schemas[-1].model_json_schema()
    allowed = schema["$defs"]["CitedField"]["enum"]
    assert "invoice_total" in allowed
    assert "invoice_vs_receipt" in allowed
    assert "calculations" not in allowed

    # Output citing anything else is impossible: the provider rejects it
    fake_llm.output["cited_fields"] = ["bank_account"]
    run = await analyzed_run(prep, invoice_number="INV-9")
    assert run["narrative"]["status"] == "failed"
