"""finance pod ar3: billing and invoicing workflow

New workflow key ar_billing; posting tasks may create a sales invoice.

Revision ID: f3b8d2a6c1e4
Revises: e1a7c3d5b9f2
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f3b8d2a6c1e4'
down_revision: Union[str, Sequence[str], None] = 'e1a7c3d5b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WORKFLOWS = ["ar_collections", "bank_recon", "fpa_trend", "treasury", "reporting",
             "ap_purchase_request", "ap_vendor_onboarding", "ap_invoice_match", "ap_month_close",
             "ar_client_account"]
TASKS = ["receive_payment", "journal_entry", "create_supplier", "create_purchase_order",
         "create_purchase_receipt", "create_journal_entry", "create_customer"]


def _replace(name: str, table: str, column: str, values: list[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    """Upgrade schema."""
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", [*WORKFLOWS, "ar_billing"])
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind",
             [*TASKS, "create_sales_invoice"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM pod_posting_tasks WHERE kind = 'create_sales_invoice'")
    op.execute("DELETE FROM pod_cases WHERE workflow = 'ar_billing'")
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind", TASKS)
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", WORKFLOWS)
