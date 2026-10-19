"""Every agent the application knows about. Add new agents to AGENTS."""

from src.app.agent_catalog.agents.ap_invoice import ApInvoiceAgent
from src.app.agent_catalog.agents.ar_collections import ArCollectionsAgent
from src.app.agent_catalog.agents.base import BaseAgent
from src.app.agent_catalog.agents.board_reporting import BoardReportingAgent
from src.app.agent_catalog.agents.cash_application import CashApplicationAgent
from src.app.agent_catalog.agents.expense_audit import ExpenseAuditAgent
from src.app.agent_catalog.agents.financial_close import FinancialCloseAgent
from src.app.agent_catalog.agents.fpa_forecast import FpaForecastAgent
from src.app.agent_catalog.agents.intercompany import IntercompanyAgent
from src.app.agent_catalog.agents.lease_accounting import LeaseAccountingAgent
from src.app.agent_catalog.agents.revenue_recognition import RevenueRecognitionAgent
from src.app.agent_catalog.agents.sox_controls import SoxControlsAgent
from src.app.agent_catalog.agents.treasury_cash import TreasuryCashAgent

AGENTS: tuple[type[BaseAgent], ...] = (
    ApInvoiceAgent,
    ExpenseAuditAgent,
    ArCollectionsAgent,
    CashApplicationAgent,
    FinancialCloseAgent,
    IntercompanyAgent,
    FpaForecastAgent,
    TreasuryCashAgent,
    RevenueRecognitionAgent,
    LeaseAccountingAgent,
    SoxControlsAgent,
    BoardReportingAgent,
)


def _index(agents: tuple[type[BaseAgent], ...]) -> dict[str, type[BaseAgent]]:
    """Fail at import time on duplicate keys or codes."""
    by_key: dict[str, type[BaseAgent]] = {}
    codes: dict[str, str] = {}
    for agent in agents:
        if agent.key in by_key:
            raise RuntimeError(f"Duplicate agent key {agent.key!r}")
        if agent.code in codes:
            raise RuntimeError(
                f"Agent code {agent.code} used by {codes[agent.code]} and {agent.key}"
            )
        by_key[agent.key] = agent
        codes[agent.code] = agent.key
    return by_key


REGISTRY: dict[str, type[BaseAgent]] = _index(AGENTS)


def get_agent_definition(key: str) -> type[BaseAgent] | None:
    return REGISTRY.get(key)
