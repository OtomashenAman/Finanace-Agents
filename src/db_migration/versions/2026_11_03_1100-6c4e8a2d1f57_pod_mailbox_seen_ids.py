"""pod mailbox cursor: mails already seen at the cursor's exact second

Revision ID: 6c4e8a2d1f57
Revises: d7e2b8c4a9f1
Create Date: 2026-11-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6c4e8a2d1f57'
down_revision: Union[str, Sequence[str], None] = 'd7e2b8c4a9f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'pod_mailbox_cursors',
        sa.Column(
            'seen_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pod_mailbox_cursors', 'seen_ids')
