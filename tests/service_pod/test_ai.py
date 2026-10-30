import ast
import pathlib

import pytest
from pydantic import BaseModel

from src.app.service_pod.ai import (
    AiOutputRejectedError,
    CitedNarrative,
    Fact,
    cited_narrative,
    extract,
    narrative_problems,
)
from tests.conftest import FakeLLM

FACTS = [
    Fact("revenue.2026-09", "September revenue", "$540,000"),
    Fact("margin.2026-09", "September operating margin", "15.74%"),
]


def test_narrative_must_cite_known_facts_and_state_no_numbers() -> None:
    good = CitedNarrative.model_validate(
        {
            "highlights": [
                {"text": "Revenue grew, led by two accounts.", "fact_ids": ["revenue.2026-09"]}
            ]
        }
    )
    assert narrative_problems(good, FACTS) == []

    bad = CitedNarrative.model_validate(
        {
            "highlights": [
                {"text": "Revenue rose 12.5% to $540k.", "fact_ids": ["revenue.2026-09"]},
                {"text": "Margins improved.", "fact_ids": ["margin.2026-10"]},
            ]
        }
    )
    problems = narrative_problems(bad, FACTS)
    assert any("states a number" in p for p in problems)
    assert any("unknown facts margin.2026-10" in p for p in problems)


async def test_cited_narrative_rejects_invented_figures() -> None:
    llm = FakeLLM()
    llm.output = {"highlights": [{"text": "Margin is 15.7%", "fact_ids": ["margin.2026-09"]}]}
    with pytest.raises(AiOutputRejectedError):
        await cited_narrative(llm, system="s", facts=FACTS, ask="Explain", prompt_version="t1")

    llm.output = {"highlights": [{"text": "Margin improved", "fact_ids": ["margin.2026-09"]}]}
    result = await cited_narrative(llm, system="s", facts=FACTS, ask="Explain", prompt_version="t1")
    assert result.provenance.as_dict() == {
        "provider": "fake",
        "model": "fake-model",
        "request_id": "req_test",
        "prompt_version": "t1",
    }
    assert "[margin.2026-09] September operating margin: 15.74%" in llm.calls[-1][1]


class _Tranche(BaseModel):
    amount: str
    quote: str


async def test_extraction_validator_stops_unsupported_output() -> None:
    llm = FakeLLM()
    llm.output = {"amount": "9000", "quote": "we will pay $6k now"}
    with pytest.raises(AiOutputRejectedError, match="not in the quote"):
        await extract(
            llm,
            system="s",
            user="u",
            schema=_Tranche,
            prompt_version="t1",
            validate=lambda t: [] if t.amount in t.quote else ["amount not in the quote"],
        )


def test_service_pod_never_writes_to_quickbooks() -> None:
    """Slide 44 gate 1: no agent write capability. The module never calls the QuickBooks
    client's write methods (or the data-source write-back)."""
    writes = {"set_bill_note", "create_bill", "stamp_bill", "_post", "write_back"}
    root = pathlib.Path("src/app/service_pod")
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not called & writes, f"{path} calls {called & writes}"
