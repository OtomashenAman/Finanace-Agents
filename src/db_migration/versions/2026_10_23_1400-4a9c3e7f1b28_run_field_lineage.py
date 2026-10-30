"""run field lineage: which input fields came from which source record

Revision ID: 4a9c3e7f1b28
Revises: 7d1e5c2b8a63
Create Date: 2026-10-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4a9c3e7f1b28'
down_revision: Union[str, Sequence[str], None] = '7d1e5c2b8a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'run_source_snapshots',
        sa.Column(
            'field_sources',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('run_source_snapshots', 'field_sources')
