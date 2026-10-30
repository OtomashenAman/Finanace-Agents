from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import Capacity, WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.AR_COLLECTIONS,
    name="AR Collections",
    prefix="AR",
    description=(
        "Customer conversations on overdue invoices: approved emails, reply "
        "understanding, supported payment commitments."
    ),
    labels={
        Capacity.PREPARER: "AR user",
        Capacity.REVIEWER: "AR Reviewer",
        Capacity.POSTER: "Finance Admin",
    },
    required=frozenset({Collection.CUSTOMERS, Collection.INVOICES}),
    visible=frozenset(
        {Collection.CUSTOMERS, Collection.INVOICES, Collection.PAYMENTS, Collection.CONTRACTS}
    ),
    final_gate=False,
)
