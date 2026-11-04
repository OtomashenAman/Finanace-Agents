"""service pod sign-off capacity: the role an approval stands for

The Finance Admin gives every Service POD sign-off; each approval records the capacity it
was given in (e.g. "Finance Head" for FP&A) so the audit trail reads like the deck.

Revision ID: a4c7e2f9b1d3
Revises: 8b3f6c1d9e20
Create Date: 2026-11-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c7e2f9b1d3'
down_revision: Union[str, Sequence[str], None] = '8b3f6c1d9e20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'pod_approvals',
        sa.Column('capacity', sa.String(length=50), server_default='Finance Admin', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pod_approvals', 'capacity')
