"""service pod snapshot sources: which data source a snapshot was read from

Snapshots never change (a trigger refuses UPDATE), so the link to the connected data source
lives in its own table. Deleting the data source "with dependents" uses it to remove the
snapshots and cases made from it. Existing QuickBooks Online snapshots are linked to the
importer's connection of the same company.

Revision ID: d7e2b8c4a9f1
Revises: c3d9a1e7f2b4
Create Date: 2026-11-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e2b8c4a9f1'
down_revision: Union[str, Sequence[str], None] = 'c3d9a1e7f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('pod_snapshot_sources',
    sa.Column('snapshot_id', sa.Uuid(), nullable=False),
    sa.Column('data_source_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['data_source_id'], ['data_sources.id'], name=op.f('fk_pod_snapshot_sources_data_source_id_data_sources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['snapshot_id'], ['pod_snapshots.id'], name=op.f('fk_pod_snapshot_sources_snapshot_id_pod_snapshots'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('snapshot_id', name=op.f('pk_pod_snapshot_sources'))
    )
    op.create_index(op.f('ix_pod_snapshot_sources_data_source_id'), 'pod_snapshot_sources', ['data_source_id'], unique=False)
    op.execute(
        """
        INSERT INTO pod_snapshot_sources (snapshot_id, data_source_id)
        SELECT DISTINCT ON (s.id) s.id, d.id
          FROM pod_snapshots s
          JOIN data_sources d
            ON d.kind = 'quickbooks' AND d.external_id = s.company_id AND d.owner_id = s.imported_by
         WHERE s.source_type = 'quickbooks_online'
         ORDER BY s.id, d.created_at DESC
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_pod_snapshot_sources_data_source_id'), table_name='pod_snapshot_sources')
    op.drop_table('pod_snapshot_sources')
