from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import Capacity, WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.FPA_TREND,
    name="FP&A Trend Intelligence",
    prefix="FPA",
    description=(
        "Month-by-month P&L trends reconciled to posted transactions, with cited "
        "drivers and Finance Head commentary."
    ),
    labels={
        Capacity.PREPARER: "FP&A Analyst",
        Capacity.REVIEWER: "Finance Head",
        Capacity.POSTER: "Finance Admin",
    },
    required=frozenset(
        {
            Collection.ACCOUNTS,
            Collection.GL_LINES,
            Collection.TRANSACTIONS,
        }
    ),
    visible=frozenset(
        {Collection.ACCOUNTS, Collection.GL_LINES, Collection.TRANSACTIONS, Collection.INVOICES}
    ),
    final_gate=False,
)
