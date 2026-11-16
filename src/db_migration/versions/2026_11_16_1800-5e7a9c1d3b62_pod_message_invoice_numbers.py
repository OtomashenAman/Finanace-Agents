"""pod messages: the invoices an email is about, when only some of the case's

Revision ID: 5e7a9c1d3b62
Revises: 8b2d4e6f1a35
Create Date: 2026-11-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5e7a9c1d3b62'
down_revision: Union[str, Sequence[str], None] = '8b2d4e6f1a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'pod_messages',
        sa.Column('invoice_numbers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pod_messages', 'invoice_numbers')
