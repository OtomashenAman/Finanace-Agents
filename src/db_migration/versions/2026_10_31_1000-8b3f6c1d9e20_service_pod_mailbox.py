"""service pod mailbox: replies read from the Microsoft 365 mailbox

How far the worker has read each mailbox, and replies it imported have no person as author.

Revision ID: 8b3f6c1d9e20
Revises: 5e1d0a7c2b94
Create Date: 2026-10-31 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b3f6c1d9e20'
down_revision: Union[str, Sequence[str], None] = '5e1d0a7c2b94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('pod_mailbox_cursors',
    sa.Column('mailbox', sa.String(length=320), nullable=False),
    sa.Column('received_after', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('mailbox', name=op.f('pk_pod_mailbox_cursors'))
    )
    op.alter_column('pod_messages', 'created_by', existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    """Downgrade schema (replies read from the mailbox have no author to restore)."""
    op.execute("DELETE FROM pod_messages WHERE created_by IS NULL")
    op.alter_column('pod_messages', 'created_by', existing_type=sa.Uuid(), nullable=False)
    op.drop_table('pod_mailbox_cursors')
