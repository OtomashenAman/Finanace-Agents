from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import Capacity, WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.REPORTING,
    name="Financial Reporting",
    prefix="RPT",
    description=(
        "The monthly management pack: comparable statements, balance checks, cited "
        "commentary, Controller review and CFO sign-off."
    ),
    labels={
        Capacity.PREPARER: "Reporting Analyst",
        Capacity.REVIEWER: "Controller",
        Capacity.FINAL_APPROVER: "CFO",
        Capacity.POSTER: "Finance Admin",
    },
    required=frozenset(
        {
            Collection.ACCOUNTS,
            Collection.GL_LINES,
            Collection.TRANSACTIONS,
            Collection.BALANCE_SHEETS,
            Collection.CLOSE_STATUS,
            Collection.INVOICES,
        }
    ),
    visible=frozenset(
        {
            Collection.ACCOUNTS,
            Collection.GL_LINES,
            Collection.TRANSACTIONS,
            Collection.BALANCE_SHEETS,
            Collection.CLOSE_STATUS,
            Collection.INVOICES,
            Collection.CUSTOMERS,
        }
    ),
    final_gate=True,
)
