"""The requirement holds the Finance POD to every L4/L5 step: a phase whose workflows are
built must have nothing missing. And the checker itself catches each kind of gap."""

from dataclasses import replace
from pathlib import Path

import pytest

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.requirements import PHASES
from src.app.finance_pod.requirements.coverage import claimed_ids, problems
from src.app.finance_pod.requirements.model import (
    L3,
    L4,
    Checkpoint,
    Item,
    ItemKind,
    MeasureReq,
    Phase,
)
from src.app.service_pod.core.steps.spec import StepKind, StepPlan
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey, WorkflowKey
from tests.finance_pod.conftest import DEMO_SPEC

TESTS = Path(__file__).parent


def _test_sources() -> str:
    return "\n".join(p.read_text() for p in TESTS.rglob("test_*.py"))


@pytest.mark.parametrize("phase", PHASES, ids=[p.id for p in PHASES])
def test_every_built_phase_covers_its_requirement(phase: Phase) -> None:
    if not phase.workflows:
        pytest.skip(f"{phase.id} {phase.title}: no workflow built yet")
    specs = [WORKFLOWS[WorkflowKey(key)] for key in phase.workflows]
    assert all(spec.pod == PodKey.FINANCE for spec in specs)
    assert problems(phase, specs, _test_sources()) == []


def test_the_transcription_is_well_formed() -> None:
    seen: set[tuple[str, str]] = set()  # the slides number AP and AR each from 1.1
    for phase in PHASES:
        ids = [i.id for i in phase.items] + [m.id for m in phase.measures]
        assert len(ids) == len(set(ids)), phase.id
        assert all(i.startswith(phase.id + ".") for i in ids), phase.id
        for task in phase.tasks():
            assert task.steps, task.code
            for code, text in task.steps:
                assert code.startswith(task.code + "."), code
                assert text.strip() == text and text, code
                assert (phase.process, code) not in seen, code
                seen.add((phase.process, code))
    assert {p.id for p in PHASES} >= {"AP1", "AP3", "AP6", "AR1", "AR3", "AR5"}


DEMO_PHASE = Phase(
    id="DM1",
    process="Demo",
    title="Demo purchase",
    pages="-",
    activities=(
        L3("1", "Demo", "Requester", "Portal", (
            L4("1.1", "Describe the need", StepKind.PERSON, (("1.1.a", "Item and quantity"),)),
            L4("1.2", "Budget agent checks", StepKind.AGENT, (("1.2.a", "Remaining budget"),)),
            L4("1.3", "Budget owner decides", StepKind.PERSON,
               (("1.3.a", "Approves, rejects or queries"),)),
            L4("1.4", "Buyer gets quotes", StepKind.PERSON, (("1.4.a", "Quotes above threshold"),)),
        )),
    ),
    items=(Item("DM1.R1", ItemKind.RULE, "Quantities above 1000 need a contract"),),
    checkpoints=(Checkpoint("Budget owner approval", Cap.BUDGET_OWNER),),
    measures=(MeasureReq("DM1.M1", "Cases"),),
)  # fmt: skip

# The demo spec names its rule and measure DEMO.*; the checker matches by id
DEMO = replace(
    DEMO_SPEC,
    plan=replace(
        DEMO_SPEC.plan,
        rules=(replace(DEMO_SPEC.plan.rules[0], id="DM1.R1"),),
        measures=(replace(DEMO_SPEC.plan.measures[0], id="DM1.M1"),),
    ),
)
MARKED = '@pytest.mark.requirement("DM1.R1")'


def test_the_checker_passes_a_complete_workflow() -> None:
    assert problems(DEMO_PHASE, [DEMO], MARKED) == []


def test_the_checker_names_every_gap() -> None:
    steps = DEMO.plan.steps
    broken = replace(
        DEMO,
        signoffs=("controller",),
        plan=StepPlan(
            steps=(
                replace(steps[0], capacity=None),  # a person's step without a capacity
                replace(steps[1], handler=None),  # an agent step without an agent
                replace(steps[2], kind=StepKind.AGENT, handler=steps[1].handler,
                        capacity=None),  # wrong kind; the checkpoint loses its holder
                # 1.4 left out entirely
            ),
            rules=(),
            measures=(),
        ),
    )  # fmt: skip
    found = problems(DEMO_PHASE, [broken], "")
    assert any("1.4.a (Quotes above threshold) isn't a step" in p for p in found)
    assert any("1.3.a: the requirement makes 1.3 a person task" in p for p in found)
    assert any("1.1 is a person's step without a capacity" in p for p in found)
    assert any("1.2 is an agent step without an agent" in p for p in found)
    assert any("checkpoint 'Budget owner approval'" in p for p in found)
    assert any(
        "DM1.R1 (rule: Quantities above 1000 need a contract) isn't implemented" in p for p in found
    )
    assert any("measure DM1.M1 (Cases) isn't computed" in p for p in found)


def test_the_checker_wants_each_rule_tested_and_the_words_kept() -> None:
    reworded = replace(
        DEMO,
        plan=replace(
            DEMO.plan,
            steps=(
                replace(DEMO.plan.steps[0], l5=(replace(DEMO.plan.steps[0].l5[0], text="Item"),)),
                *DEMO.plan.steps[1:],
            ),
        ),
    )
    found = problems(DEMO_PHASE, [reworded], "")
    assert any("1.1.a: text 'Item' differs" in p for p in found)
    assert any('DM1.R1 has no test marked @pytest.mark.requirement("DM1.R1")' in p for p in found)


def test_out_of_scope_items_need_no_implementation() -> None:
    phase = replace(
        DEMO_PHASE,
        items=(replace(DEMO_PHASE.items[0], out_of_scope="Needs GIA's IRS registration"),),
    )
    without_rules = replace(DEMO, plan=replace(DEMO.plan, rules=()))
    assert problems(phase, [without_rules], "") == []


def test_markers_are_read_from_test_sources() -> None:
    src = '@pytest.mark.requirement("AP1.R1", "AP1.G2")\n@pytest.mark.requirement(\'AP3.R1\')'
    assert claimed_ids(src) == {"AP1.R1", "AP1.G2", "AP3.R1"}
