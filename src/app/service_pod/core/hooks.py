"""Where each workflow plugs its own rules into the shared case engine.

The engine (cases, messaging, posting tasks) looks a workflow's hooks up here; each flow
package registers its own through core.registry. Nothing here imports the flows, so there
is no cycle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.app.core.llm.base import LLMProvider
    from src.app.service_pod.core.cases.models import PodCase
    from src.app.service_pod.core.cases.service import ActionSpec, Ctx
    from src.app.service_pod.core.messaging.models import PodMessage
    from src.app.service_pod.core.snapshots.contract import SnapshotDocument
    from src.app.service_pod.core.tasks.models import PodPostingTask


class Composed(BaseModel):
    """A suggested draft: the fact block is the source's figures, the rest is wording."""

    to_email: str | None
    to_name: str | None
    subject: str
    body: str
    fact_block: str | None
    ai_drafted: bool  # False: a fixed template (no AI configured, or it failed)
    note: str | None = None


@dataclass(frozen=True)
class WorkflowHooks:
    # Extra case actions: name -> spec (same contract as the engine's own)
    actions: Mapping[str, ActionSpec] = field(default_factory=dict)
    # Once the new case has its ID (e.g. raise review tasks the source calls for)
    after_create: Callable[[AsyncSession, PodCase], Awaitable[None]] | None = None
    # Check the selection against the snapshot and compute the case's state (raise to refuse).
    # refresh=True: the case moves to a newer snapshot (e.g. an invoice may now be paid)
    on_create: Callable[[AsyncSession, PodCase, SnapshotDocument, bool], Awaitable[None]] | None = (
        None
    )
    # Workflow-specific reasons the case can't be submitted / approved yet
    blockers: Callable[[Ctx], Awaitable[list[str]]] | None = None
    # Message purposes the workflow drafts (purpose -> label)
    purposes: Mapping[str, str] = field(default_factory=dict)
    # The verified fact block a message of this purpose must carry (None: no facts)
    facts: Callable[[AsyncSession, PodCase, str], Awaitable[str | None]] | None = None
    # Why a message of this purpose can't be drafted now (None: it can)
    draft_blocker: Callable[[AsyncSession, PodCase, str], Awaitable[str | None]] | None = None
    compose: Callable[[AsyncSession, PodCase, str, LLMProvider], Awaitable[Composed]] | None = None
    # Read an imported reply into commitments / allocations / review tasks
    extract_reply: (
        Callable[[AsyncSession, PodCase, PodMessage, LLMProvider], Awaitable[None]] | None
    ) = None
    # One line about a case, shown on related cases of other workflows (same customer)
    summary: Callable[[AsyncSession, PodCase], Awaitable[str | None]] | None = None
    # The step an open case is on (the frontend's step keys), for the workflow's worklists
    stage: Callable[[AsyncSession, PodCase], Awaitable[str]] | None = None
    # Where a draft case stands for the dashboard ("compose", "waiting", "analysis", "review",
    # "ready"); None: the engine's default, from the case's emails and review tasks
    phase: Callable[[AsyncSession, PodCase, list[str]], Awaitable[str]] | None = None
    # Workflow reasons an approved case can't be completed yet
    completion_blockers: Callable[[AsyncSession, PodCase], Awaitable[list[str]]] | None = None
    # Extra problems verifying a posting: (task, case, source it started from, fresh source)
    verify_posting: (
        Callable[[PodPostingTask, PodCase, SnapshotDocument, SnapshotDocument], list[str]] | None
    ) = None


HOOKS: dict[WorkflowKey, WorkflowHooks] = {}
_NONE = WorkflowHooks()


def hooks_for(key: WorkflowKey) -> WorkflowHooks:
    return HOOKS.get(key, _NONE)
