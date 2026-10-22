"""Shared helpers for agent engine tests: validate input, run analyze(), inspect the findings.

analysis = await run_analysis(db, TreasuryCashAgent, {**PDF_EXAMPLE, "opening_cash": "0"})
assert codes(analysis)["LIQUIDITY_BUFFER"] == "high"
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis, AnalysisContext, BaseAgent
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.runs.models import AgentRun
from src.app.data_sources.access import FinanceData


async def run_analysis(
    db: AsyncSession,
    agent: type[BaseAgent],
    values: dict[str, Any],
    *,
    documents: int = 0,
    policy: dict[str, Any] | PolicySettings | None = None,
) -> Analysis:
    """analyze() for a fresh run of a preparer without data sources (policy: code defaults)."""
    assert agent.input_schema is not None, f"{agent.__name__} has no workspace"
    data = agent.input_schema.model_validate(values)
    if isinstance(policy, dict):
        assert agent.policy_schema is not None, f"{agent.__name__} has no policy"
        policy = agent.policy_schema.model_validate(policy)
    run = AgentRun(id=uuid.uuid4(), run_number=1)
    no_sources = FinanceData(db, uuid.uuid4(), None)
    ctx = AnalysisContext(
        session=db, run=run, document_count=documents, data=no_sources, policy=policy
    )
    return await agent.analyze(data, ctx)


def codes(analysis: Analysis) -> dict[str, str]:
    """Finding code -> severity, e.g. {"PO_MATCH": "pass", "RECEIPT_MISMATCH": "high"}."""
    return {f.code: f.severity.value for f in analysis.findings}


def calculation(analysis: Analysis, key: str) -> Any:
    """One calculation's value by key."""
    return next(c.value for c in analysis.calculations if c.key == key)
