"""Treasury, Financial Close, Board Reporting and SOX through the generic run API, end to end."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.board_reporting.models import BoardReportingRun
from src.app.agent_catalog.agents.financial_close.models import FinancialCloseRun
from src.app.agent_catalog.agents.sox_controls.models import SoxControlsRun
from src.app.agent_catalog.agents.treasury_cash.models import TreasuryCashRun
from src.app.agent_catalog.models import AgentCapacity
from src.app.agent_catalog.runs.models import AgentRunDetail
from src.app.auth.models import UserRole
from tests.agent_catalog import test_board_reporting_engine as board
from tests.agent_catalog import test_financial_close_engine as close
from tests.agent_catalog import test_sox_controls_engine as sox
from tests.agent_catalog import test_treasury_cash_engine as treasury
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

pytestmark = pytest.mark.usefixtures("synced_agents")

# key, PDF example input, headline, business reference, run table, (computed column, value)
CASES: list[tuple[str, dict[str, Any], str, str | None, type[AgentRunDetail], str, Decimal]] = [
    ("treasury_cash", treasury.PDF_EXAMPLE, "Liquidity shortfall", None,
     TreasuryCashRun, "funding_gap", Decimal("25000.00")),
    ("financial_close", close.PDF_EXAMPLE, "Material close variance", "1200-AR-Control",
     FinancialCloseRun, "unexplained_difference", Decimal("1000.00")),
    ("board_reporting", board.PDF_EXAMPLE, "Source references missing", "Q3 Board Pack",
     BoardReportingRun, "revenue_growth_pct", Decimal("11.11")),
    ("sox_controls", sox.PDF_EXAMPLE, "Control exceptions found", "SOX-AP-003",
     SoxControlsRun, "exception_rate_pct", Decimal("8.00")),
]  # fmt: skip


@pytest.mark.parametrize(
    ("key", "example", "headline", "reference", "run_model", "column", "value"),
    CASES,
    ids=[c[0] for c in CASES],
)
async def test_pdf_example_input_result_review(
    key: str,
    example: dict[str, Any],
    headline: str,
    reference: str | None,
    run_model: type[AgentRunDetail],
    column: str,
    value: Decimal,
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
    assert run["priority"] == "high"
    assert run["business_reference"] == reference
    assert run["narrative"]["status"] == "ok", run["narrative"]

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


async def test_new_agents_have_workspaces_and_policies(
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
    assert "financial_close" not in policies  # materiality is entered per run
