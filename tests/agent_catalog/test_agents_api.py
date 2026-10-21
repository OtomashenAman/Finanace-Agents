"""Every agent except AP Invoice (see test_runs_api) through the generic run API, end to end."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ar_collections.models import ArCollectionsRun
from src.app.agent_catalog.agents.board_reporting.models import BoardReportingRun
from src.app.agent_catalog.agents.cash_application.models import CashApplicationRun
from src.app.agent_catalog.agents.expense_audit.models import ExpenseAuditRun
from src.app.agent_catalog.agents.financial_close.models import FinancialCloseRun
from src.app.agent_catalog.agents.fpa_forecast.models import FpaForecastRun
from src.app.agent_catalog.agents.intercompany.models import IntercompanyRun
from src.app.agent_catalog.agents.sox_controls.models import SoxControlsRun
from src.app.agent_catalog.agents.treasury_cash.models import TreasuryCashRun
from src.app.agent_catalog.models import AgentCapacity
from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.auth.models import UserRole
from tests.agent_catalog import test_ar_collections_engine as ar
from tests.agent_catalog import test_board_reporting_engine as board
from tests.agent_catalog import test_cash_application_engine as cash
from tests.agent_catalog import test_expense_audit_engine as expense
from tests.agent_catalog import test_financial_close_engine as close
from tests.agent_catalog import test_fpa_forecast_engine as fpa
from tests.agent_catalog import test_intercompany_engine as ic
from tests.agent_catalog import test_sox_controls_engine as sox
from tests.agent_catalog import test_treasury_cash_engine as treasury
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

pytestmark = pytest.mark.usefixtures("synced_agents")

# key, PDF example input, headline, priority, business reference, run table,
# (computed column, stored value)
CASES: list[tuple[str, dict[str, Any], str, str, str | None, type[AgentRunDetail], str, Any]] = [
    ("expense_audit", expense.PDF_EXAMPLE, "Policy exception", "high", "Jordan Smith",
     ExpenseAuditRun, "over_limit_amount", Decimal("85.00")),
    ("ar_collections", ar.PDF_EXAMPLE, "Collections priority", "normal", "Harbor Distribution",
     ArCollectionsRun, "priority_score", 40),
    ("cash_application", cash.PDF_EXAMPLE, "Short payment", "high", "WIRE-2901",
     CashApplicationRun, "short_payment", Decimal("100.00")),
    ("financial_close", close.PDF_EXAMPLE, "Material close variance", "high", "1200-AR-Control",
     FinancialCloseRun, "unexplained_difference", Decimal("1000.00")),
    ("intercompany", ic.PDF_EXAMPLE, "Intercompany mismatch", "high", "US Subsidiary",
     IntercompanyRun, "difference", Decimal("1000.00")),
    ("fpa_forecast", fpa.PDF_EXAMPLE, "Budget variance", "high", "North America",
     FpaForecastRun, "scenario_value", Decimal("124920.00")),
    ("treasury_cash", treasury.PDF_EXAMPLE, "Liquidity shortfall", "high", None,
     TreasuryCashRun, "funding_gap", Decimal("25000.00")),
    ("sox_controls", sox.PDF_EXAMPLE, "Control exceptions found", "high", "SOX-AP-003",
     SoxControlsRun, "exception_rate_pct", Decimal("8.00")),
    ("board_reporting", board.PDF_EXAMPLE, "Source references missing", "high", "Q3 Board Pack",
     BoardReportingRun, "revenue_growth_pct", Decimal("11.11")),
]  # fmt: skip
DRAFTING = {"expense_audit", "ar_collections"}


@pytest.mark.parametrize(
    ("key", "example", "headline", "priority", "reference", "run_model", "column", "value"),
    CASES,
    ids=[c[0] for c in CASES],
)
async def test_pdf_example_input_result_review(
    key: str,
    example: dict[str, Any],
    headline: str,
    priority: str,
    reference: str | None,
    run_model: type[AgentRunDetail],
    column: str,
    value: Any,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    preparer = await make_user(f"{key}.user@example.com", UserRole.USER)
    await assign(db, preparer, AgentCapacity.PREPARER, key=key)
    prep = await signed_in_client(preparer)
    admin = await signed_in_client(await make_user("cfo@example.com", UserRole.FINANCE_ADMIN))
    runs = f"/api/v1/agents/{key}/runs"
    first_field = next(iter(example))
    fake_llm.output = {**fake_llm.output, "cited_fields": [first_field]}
    if key in DRAFTING:  # these agents' output schema requires the draft
        fake_llm.output["draft_message"] = "Hello, could you share an update on this item?"

    form = (await prep.get(f"/api/v1/agents/{key}/form")).json()
    assert set(example) <= {f["name"] for f in form["fields"]}
    assert form["controls"]

    # A half-filled draft saves; the rest is validated on analyze
    run = (await prep.post(runs)).json()
    r = await prep.put(f"{runs}/{run['id']}/input", json={"values": {first_field: None}})
    assert r.status_code == 200, r.text
    r = await prep.post(f"{runs}/{run['id']}/analyze")
    assert r.json()["status"] == "validation_failed", r.text

    r = await prep.put(f"{runs}/{run['id']}/input", json={"values": example})
    assert r.status_code == 200, r.text
    run = (await prep.post(f"{runs}/{run['id']}/analyze")).json()
    assert run["status"] == "analyzed", run
    assert run["headline"] == headline
    assert run["priority"] == priority
    assert run["business_reference"] == reference
    assert run["narrative"]["status"] == "ok", run["narrative"]
    draft = run["narrative"]["output"]["draft_message"]
    assert (draft is not None) == (key in DRAFTING)

    detail = await db.get(run_model, run["id"])
    assert detail is not None
    assert getattr(detail, column) == value

    run = (await prep.post(f"{runs}/{run['id']}/submit")).json()
    assert run["status"] == "pending_approval", run
    r = await admin.post(
        f"{runs}/{run['id']}/reviews", json={"decision": "approved", "comment": "Checked"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


async def test_agents_have_workspaces_and_policies(
    make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    admin = await signed_in_client(await make_user("cfo@example.com", UserRole.FINANCE_ADMIN))
    agents = {a["key"]: a["has_workspace"] for a in (await admin.get("/api/v1/agents")).json()}
    for key, *_ in CASES:
        assert agents[key] is True

    policies = {
        p["agent_key"]: {f["name"]: f["kind"] for f in p["fields"]}
        for p in (await admin.get("/api/v1/admin/governance/policies")).json()
    }
    assert policies["sox_controls"] == {
        "minimum_sample_size": "number",
        "tolerable_exceptions": "number",
    }
    assert policies["board_reporting"] == {"revenue_change_review_pct": "percent"}
    assert policies["ar_collections"] == {
        "high_exposure_amount": "money",
        "reminder_score": "number",
        "escalate_score": "number",
    }
    assert set(policies["fpa_forecast"]) == {"variance_materiality_pct", "scenario_review_pct"}
    # Thresholds are entered on each run for these
    assert "financial_close" not in policies
    assert "intercompany" not in policies
