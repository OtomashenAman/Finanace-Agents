"""What every Service POD workflow declares: its key, name and the source data it needs.

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


@dataclass(frozen=True)
class WorkflowSpec:
    key: WorkflowKey
    name: str
    prefix: str  # case references: AR-0042
    description: str
    required: frozenset[Collection]  # a case can't start on a snapshot without these


# Filled by core.registry.register() as each flow package is imported (in import order)
WORKFLOWS: dict[WorkflowKey, WorkflowSpec] = {}
