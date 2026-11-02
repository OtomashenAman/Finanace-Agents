"""finance pod ap3: invoice matching workflow and receipt postings

New workflow key ap_invoice_match; posting tasks may create a purchase receipt (a receiver
confirmed the delivery).

Revision ID: b7d1e3a9c4f2
Revises: aee67f14dd47
Create Date: 2026-11-03 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7d1e3a9c4f2'
down_revision: Union[str, Sequence[str], None] = 'aee67f14dd47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WORKFLOWS = ["ar_collections", "bank_recon", "fpa_trend", "treasury", "reporting",
             "ap_purchase_request", "ap_vendor_onboarding"]
TASKS = ["receive_payment", "journal_entry", "create_supplier", "create_purchase_order"]


def _replace(name: str, table: str, column: str, values: list[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    """Upgrade schema."""
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", [*WORKFLOWS, "ap_invoice_match"])
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind",
             [*TASKS, "create_purchase_receipt"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM pod_posting_tasks WHERE kind = 'create_purchase_receipt'")
    op.execute("DELETE FROM pod_cases WHERE workflow = 'ap_invoice_match'")
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", WORKFLOWS)
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind", TASKS)
