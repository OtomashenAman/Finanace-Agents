"""What every Service POD workflow declares: its key, roles and the source data it needs.

The specs themselves live with each workflow (flows/<workflow>/spec.py) and are added to
WORKFLOWS by core.registry when the flows package is imported.
"""

from dataclasses import dataclass
from enum import StrEnum

from src.app.service_pod.core.snapshots.contract import Collection


class WorkflowKey(StrEnum):
    AR_COLLECTIONS = "ar_collections"
    BANK_RECON = "bank_recon"
    FPA_TREND = "fpa_trend"
    TREASURY = "treasury"
    REPORTING = "reporting"


class Capacity(StrEnum):
    PREPARER = "preparer"  # opens cases, drafts messages, imports replies
    REVIEWER = "reviewer"  # approves messages, commitments, results (first gate)
    FINAL_APPROVER = "final_approver"  # independent final sign-off (CFO)
    POSTER = "poster"  # Finance Admin: imports sources, performs and verifies manual posting


@dataclass(frozen=True)
class WorkflowSpec:
    key: WorkflowKey
    name: str
    prefix: str  # case references: AR-0042
    description: str
    # Deck role names, for screens and the assignments page
    labels: dict[Capacity, str]
    required: frozenset[Collection]  # a case can't start on a snapshot without these
    visible: frozenset[Collection]  # what its users may read of a snapshot
    final_gate: bool  # True: a different user gives the final approval after the review

    @property
    def capacities(self) -> tuple[Capacity, ...]:
        return tuple(self.labels)


# Filled by core.registry.register() as each flow package is imported (in import order)
WORKFLOWS: dict[WorkflowKey, WorkflowSpec] = {}
