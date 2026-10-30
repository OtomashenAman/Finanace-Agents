"""The shared system prompt and each agent's prompt.py."""

import importlib
import re
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ap_invoice import ApInvoiceAgent
from src.app.agent_catalog.agents.ap_invoice.models import ApInvoiceRun
from src.app.agent_catalog.agents.ap_invoice.schemas import ApInvoiceInput
from src.app.agent_catalog.agents.base import BaseAgent
from src.app.agent_catalog.models import AgentCapacity
from src.app.agent_catalog.registry import AGENTS
from src.app.agent_catalog.runs import prompts
from src.app.agent_catalog.runs.models import RunNarrative
from src.app.auth.models import UserRole
from tests.agent_catalog.test_runs_api import analyzed_run, assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

WORKSPACE_AGENTS = [a for a in AGENTS if a.has_workspace()]


def test_system_prompt_puts_shared_rules_before_the_agent_guidance() -> None:
    text = prompts.system_prompt("Treasury", "Explain the cash bridge.\n")

    assert text.startswith(prompts.ROLE)
    for rule in prompts.RULES + prompts.OUTPUT_RULES:
        assert f"- {rule}" in text
    assert text.endswith("Agent: Treasury\nExplain the cash bridge.")
    assert text.index("Never calculate") < text.index("Agent: Treasury")


def test_prompt_version_combines_system_and_agent() -> None:
    assert prompts.prompt_version("sox_controls/v3") == "narrative/v1+sox_controls/v3"
    # Fits RunNarrative.prompt_version (String(50)) for every agent
    assert all(len(prompts.prompt_version(a.prompt_version)) <= 50 for a in WORKSPACE_AGENTS)


@pytest.mark.parametrize("agent", WORKSPACE_AGENTS, ids=lambda a: a.key)
def test_every_workspace_agent_takes_its_guidance_from_prompt_py(agent: type[BaseAgent]) -> None:
    module: Any = importlib.import_module(f"src.app.agent_catalog.agents.{agent.key}.prompt")
    assert agent.narrative_guidance == module.GUIDANCE
    assert agent.prompt_version == module.PROMPT_VERSION
    assert re.fullmatch(rf"{agent.key}/v\d+", agent.prompt_version)


def test_workspace_agent_without_guidance_or_version_is_rejected() -> None:
    meta = {
        "code": "99",
        "name": "Test",
        "short_name": "Test",
        "description": "Test",
        "primary_user": "Analyst",
        "reviewer": "Approver",
        "input_schema": ApInvoiceInput,
        "run_model": ApInvoiceRun,
    }
    with pytest.raises(TypeError, match="no narrative_guidance"):
        type("NoGuidance", (BaseAgent,), {**meta, "key": "no_guidance"})
    with pytest.raises(TypeError, match="must look like 'bad_version/v1'"):
        type(
            "BadVersion",
            (BaseAgent,),
            {**meta, "key": "bad_version", "narrative_guidance": "x", "prompt_version": "v1"},
        )


@pytest.mark.usefixtures("synced_agents")
async def test_narrative_records_the_combined_prompt_version(
    make_user: MakeUser, signed_in_client: ClientFactory, fake_llm: FakeLLM, db: AsyncSession
) -> None:
    preparer = await make_user("ap.user@example.com", UserRole.USER)
    await assign(db, preparer, AgentCapacity.PREPARER)
    run = await analyzed_run(await signed_in_client(preparer))

    assert run["narrative"]["prompt_version"] == "narrative/v1+ap_invoice/v1"
    stored = await db.scalar(select(RunNarrative.prompt_version))
    assert stored == "narrative/v1+ap_invoice/v1"
    system, _ = fake_llm.calls[0]
    assert system == prompts.system_prompt(ApInvoiceAgent.name, ApInvoiceAgent.narrative_guidance)
    assert "What the AP approver should verify" in system
