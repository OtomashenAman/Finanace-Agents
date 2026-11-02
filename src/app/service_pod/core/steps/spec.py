"""What a workflow declares about its steps: the requirement's L4 tasks and L5 steps.

A workflow with steps (the Finance POD's) can't be approved or completed while any L5 step is
pending or failed, and a step that doesn't apply is recorded as such with its reason, never
left out. The engine (steps.service) enforces order, capacity and segregation of duties.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.service_pod.core.cases.models import PodCase
    from src.app.service_pod.core.cases.service import Ctx

OWNER = "owner"  # in distinct_from: whoever opened the case


class StepKind(StrEnum):
    """The requirement's colours: blue agent, gold person, grey system, white manual."""

    AGENT = "agent"
    PERSON = "person"
    SYSTEM = "system"
    MANUAL = "manual"


class StepStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


SETTLED = frozenset({StepStatus.DONE, StepStatus.NOT_APPLICABLE})


class StepFailedError(Exception):
    """Raised by an agent handler: the step is recorded as failed with this reason (shown to
    the people on the case); a person reruns it once the cause is fixed."""


class StepResult(BaseModel):
    """Default L5 result: done, with an optional note. Workflows declare richer models."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=4000)


@dataclass(frozen=True)
class L5Spec:
    code: str  # e.g. "1.2.1.a"
    text: str  # the requirement's own words
    result: type[BaseModel] = StepResult


# Why a step doesn't apply to this case (None: it applies), e.g. "Below the quote threshold"
Applies = Callable[["Ctx"], Awaitable[str | None]]
# An agent step's work: returns each L5 code's result; raise to fail the step
AgentHandler = Callable[["Ctx", "StepSpec"], Awaitable[dict[str, BaseModel]]]


@dataclass(frozen=True)
class StepSpec:
    key: str  # unique within the workflow; usually the L4 code ("1.2.1")
    l4: str  # the requirement's L4 code (two steps may share one, e.g. 1.5.2 a / b)
    title: str
    kind: StepKind
    l5: tuple[L5Spec, ...]
    capacity: str | None = None  # who completes a PERSON / MANUAL step
    after: tuple[str, ...] = ()  # step keys that must be settled first
    # Step keys (or OWNER) whose person may not complete this one: segregation of duties
    distinct_from: tuple[str, ...] = ()
    not_applicable_when: Applies | None = None
    handler: AgentHandler | None = None  # AGENT steps


@dataclass(frozen=True)
class Rule:
    """A business rule, guardrail or pain point from the requirement. `check` returns why
    the case can't be approved (None: fine); rules enforced at a specific action (e.g.
    refusing a posting) say so in `enforced_by` and leave check out."""

    id: str  # the requirement map's id, e.g. "AP1.R1"
    text: str
    check: Callable[[Ctx], Awaitable[str | None]] | None = None
    enforced_by: str | None = None


@dataclass(frozen=True)
class Measure:
    id: str  # the requirement map's id, e.g. "AP1.M1"
    label: str
    unit: str  # "hours", "days", "%", "count"
    compute: Callable[[AsyncSession, list[PodCase]], Awaitable[Decimal | None]]


@dataclass(frozen=True)
class StepPlan:
    """Everything a workflow declares about its steps, rules and measures."""

    steps: tuple[StepSpec, ...] = ()
    rules: tuple[Rule, ...] = ()
    measures: tuple[Measure, ...] = ()
    # Capacities that see every case of the workflow (others see the cases they opened)
    viewers: frozenset[str] = field(default_factory=frozenset)
    # Capacities that may open a case
    openers: frozenset[str] = field(default_factory=frozenset)

    def step(self, key: str) -> StepSpec | None:
        return next((s for s in self.steps if s.key == key), None)

    def capacities(self) -> set[str]:
        return (
            {s.capacity for s in self.steps if s.capacity} | set(self.viewers) | set(self.openers)
        )
