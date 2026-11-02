"""finance pod erpnext: ERPNext connections, snapshots and app-posted tasks

data_sources gets kind 'erpnext' and base_url (the site's address; the API key and secret
use client_id / client_secret_enc). pod_snapshots gets source type 'erpnext' and provenance
'ERP_READONLY_EXPORT'. pod_posting_tasks gets the kinds the app posts to the ERP itself
(create_supplier, create_purchase_order).

Revision ID: 9c4e1f7a2b65
Revises: 3b4435166a5c
Create Date: 2026-11-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c4e1f7a2b65'
down_revision: Union[str, Sequence[str], None] = '3b4435166a5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECKS = {
    # constraint, table, column: (values before, values after)
    ("ck_data_sources_kind", "data_sources", "kind"): (
        ["quickbooks", "upload"],
        ["quickbooks", "upload", "erpnext"],
    ),
    ("ck_pod_snapshots_source_type", "pod_snapshots", "source_type"): (
        ["json_export", "bank_csv", "quickbooks_online", "qbxml"],
        ["json_export", "bank_csv", "quickbooks_online", "qbxml", "erpnext"],
    ),
    ("ck_pod_snapshots_provenance", "pod_snapshots", "provenance"): (
        ["QUICKBOOKS_READONLY_EXPORT", "SYNTHETIC_DEMO"],
        ["QUICKBOOKS_READONLY_EXPORT", "SYNTHETIC_DEMO", "ERP_READONLY_EXPORT"],
    ),
    ("ck_pod_posting_tasks_kind", "pod_posting_tasks", "kind"): (
        ["receive_payment", "journal_entry"],
        ["receive_payment", "journal_entry", "create_supplier", "create_purchase_order"],
    ),
}


def _replace(name: str, table: str, column: str, values: list[str]) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    # The naming convention would prefix it again: give the final name as-is
    op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("data_sources", sa.Column("base_url", sa.String(length=500), nullable=True))
    for (name, table, column), (_, after) in CHECKS.items():
        _replace(name, table, column, after)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM pod_posting_tasks WHERE kind IN ('create_supplier', 'create_purchase_order')")
    op.execute("DELETE FROM data_sources WHERE kind = 'erpnext'")
    for (name, table, column), (before, _) in CHECKS.items():
        _replace(name, table, column, before)
    op.drop_column("data_sources", "base_url")
