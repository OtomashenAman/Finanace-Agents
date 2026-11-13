"""user areas: which parts of the app (Agent Catalog, Service POD, Finance POD) each person
has; everyone keeps what their role gave them

Revision ID: 3c8e1f2a9d47
Revises: 1ed5d5ea2388
Create Date: 2026-11-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3c8e1f2a9d47'
down_revision: Union[str, Sequence[str], None] = '1ed5d5ea2388'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column(
            'areas',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'["agent_catalog", "service_pod", "finance_pod"]\'::jsonb'
            ),
            nullable=False,
        ),
    )
    # The PODs are for Finance Admins only
    op.execute(
        "UPDATE users SET areas = '[\"agent_catalog\"]'::jsonb WHERE role <> 'finance_admin'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'areas')
