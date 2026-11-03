"""finance pod ap6: month-end close workflow, journal postings, statements and evidence

New workflow key ap_month_close; posting tasks may create a journal entry (an accrual and its
reversal); documents may be vendor statements and filed evidence packs.

Revision ID: c8e2f4b1d5a3
Revises: b7d1e3a9c4f2
Create Date: 2026-11-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c8e2f4b1d5a3'
down_revision: Union[str, Sequence[str], None] = 'b7d1e3a9c4f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WORKFLOWS = ["ar_collections", "bank_recon", "fpa_trend", "treasury", "reporting",
             "ap_purchase_request", "ap_vendor_onboarding", "ap_invoice_match"]
TASKS = ["receive_payment", "journal_entry", "create_supplier", "create_purchase_order",
         "create_purchase_receipt"]
KINDS = ["timesheet", "invoice_copy", "msa", "supporting", "other", "quote", "tax_form",
         "bank_letter", "compliance"]


def _replace(name: str, table: str, column: str, values: list[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    """Upgrade schema."""
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", [*WORKFLOWS, "ap_month_close"])
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind",
             [*TASKS, "create_journal_entry"])
    _replace("ck_pod_artifacts_kind", "pod_artifacts", "kind",
             [*KINDS, "vendor_statement", "evidence"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM pod_artifacts WHERE kind IN ('vendor_statement', 'evidence')")
    op.execute("DELETE FROM pod_posting_tasks WHERE kind = 'create_journal_entry'")
    op.execute("DELETE FROM pod_cases WHERE workflow = 'ap_month_close'")
    _replace("ck_pod_artifacts_kind", "pod_artifacts", "kind", KINDS)
    _replace("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind", TASKS)
    _replace("ck_pod_cases_workflow", "pod_cases", "workflow", WORKFLOWS)
