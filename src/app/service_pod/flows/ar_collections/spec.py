from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.AR_COLLECTIONS,
    name="AR Collections",
    prefix="AR",
    description=(
        "Customer conversations on overdue invoices: approved emails, reply "
        "understanding, supported payment commitments."
    ),
    required=frozenset({Collection.CUSTOMERS, Collection.INVOICES}),
)
