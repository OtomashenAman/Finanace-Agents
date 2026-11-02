"""The requirement as data: one Phase per slide pair of the GIA L4/L5 drill-down.

Only the future-state (To-Be) slide defines what is built: its L3 activities, L4 tasks (with
the slide's colour: agent, person, system) and L5 steps, its guardrails, human checkpoints
and measures. From the current-state (As-Is) slide come the business rules that still hold
and the pain points; each pain point is either addressed by a rule or recorded as out of
scope with a reason. tests/finance_pod/test_requirement_coverage.py holds the workflows to it.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from src.app.service_pod.core.steps.spec import StepKind


class ItemKind(StrEnum):
    RULE = "rule"  # As-Is business rule that still applies
    GUARDRAIL = "guardrail"  # To-Be guardrail
    PAIN_POINT = "pain_point"  # As-Is exception / pain point the design must answer


@dataclass(frozen=True)
class L4:
    code: str  # e.g. "1.2.1"
    title: str
    kind: StepKind
    steps: tuple[tuple[str, str], ...]  # (L5 code, text)


@dataclass(frozen=True)
class L3:
    code: str  # e.g. "1.2"
    title: str
    who: str
    system: str
    tasks: tuple[L4, ...]


@dataclass(frozen=True)
class Item:
    id: str  # e.g. "AP1.R1": phase, kind letter, number
    kind: ItemKind
    text: str
    # Not implemented on purpose: why (shown on screens and in the coverage report)
    out_of_scope: str | None = None


@dataclass(frozen=True)
class Checkpoint:
    text: str
    capacity: str  # the capacity that must hold the step


@dataclass(frozen=True)
class MeasureReq:
    id: str  # e.g. "AP1.M1"
    text: str


@dataclass(frozen=True)
class Phase:
    id: str  # "AP1"
    process: str  # "Procure-to-Pay (Accounts Payable)"
    title: str
    pages: str  # where it is in the PDF
    activities: tuple[L3, ...]
    items: tuple[Item, ...] = ()
    checkpoints: tuple[Checkpoint, ...] = ()
    measures: tuple[MeasureReq, ...] = ()
    # The workflow keys that implement it (empty: not built yet, the test skips it)
    workflows: tuple[str, ...] = field(default=())

    def tasks(self) -> list[L4]:
        return [task for activity in self.activities for task in activity.tasks]

    def l5_codes(self) -> list[str]:
        return [code for task in self.tasks() for code, _ in task.steps]
