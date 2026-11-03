"""finance pod ar1: client account and credit set-up workflow

New workflow key ar_client_account; posting tasks may create a customer (the client with its
approved credit terms); documents may arrive through the client portal.

Revision ID: e1a7c3d5b9f2
Revises: c8e2f4b1d5a3
Create Date: 2026-11-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e1a7c3d5b9f2'
down_revision: Union[str, Sequence[str], None] = 'c8e2f4b1d5a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WORKFLOWS = ["ar_collections", "bank_recon", "fpa_trend", "treasury", "reporting",
             "ap_purchase_request", "ap_vendor_onboarding", "ap_invoice_match", "ap_month_close"]
TASKS = ["receive_payment", "journal_entry", "create_supplier", "create_purchase_order",
         "create_purchase_receipt", "create_journal_entry"]
CHANNELS = ["upload", "vendor_portal", "email"]


def _replace(name: str, table: str, column: str, values: list[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    """Upgrade schema."""
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", [*WORKFLOWS, "ar_client_account"])
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind", [*TASKS, "create_customer"])
    _replace("ck_pod_artifacts_channel", "pod_artifacts", "channel", [*CHANNELS, "client_portal"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM pod_artifacts WHERE channel = 'client_portal'")
    op.execute("DELETE FROM pod_posting_tasks WHERE kind = 'create_customer'")
    op.execute("DELETE FROM pod_cases WHERE workflow = 'ar_client_account'")
    _replace("ck_pod_artifacts_channel", "pod_artifacts", "channel", CHANNELS)
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind", TASKS)
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", WORKFLOWS)
