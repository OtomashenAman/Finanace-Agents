import importlib
import inspect
import pkgutil

import pytest

from src.app.agent_catalog import agents as agents_pkg
from src.app.agent_catalog.agents.base import BaseAgent
from src.app.agent_catalog.registry import AGENTS, REGISTRY


def _agent_classes_in_package() -> list[type[BaseAgent]]:
    found = []
    for module_info in pkgutil.iter_modules(agents_pkg.__path__):
        if module_info.name == "base":
            continue
        module = importlib.import_module(f"{agents_pkg.__name__}.{module_info.name}")
        classes = [
            obj
            for obj in vars(module).values()
            if inspect.isclass(obj) and issubclass(obj, BaseAgent) and obj is not BaseAgent
        ]
        assert len(classes) == 1, f"{module_info.name}.py must define exactly one agent"
        found.append(classes[0])
    return found


def test_every_agent_module_is_registered() -> None:
    """Guards against adding agents/<x>.py and forgetting registry.AGENTS."""
    in_package = set(_agent_classes_in_package())
    assert in_package == set(AGENTS)


def test_registry_has_the_12_agents_with_unique_keys_and_codes() -> None:
    assert len(REGISTRY) == 12
    assert len({a.code for a in AGENTS}) == 12
    assert [a.code for a in AGENTS] == [f"{n:02d}" for n in range(1, 13)]


def test_agent_definition_requires_all_fields() -> None:
    with pytest.raises(TypeError, match="missing: reviewer"):

        class Incomplete(BaseAgent):
            key = "incomplete"
            code = "99"
            name = "Incomplete"
            short_name = "Incomplete"
            description = "No reviewer"
            primary_user = "Someone"


def test_agent_key_must_be_snake_case() -> None:
    with pytest.raises(TypeError, match="snake_case"):

        class BadKey(BaseAgent):
            key = "Bad-Key"
            code = "98"
            name = short_name = description = primary_user = reviewer = "x"
