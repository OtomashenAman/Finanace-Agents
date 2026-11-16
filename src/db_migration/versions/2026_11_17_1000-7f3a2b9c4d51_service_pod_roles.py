"""service pod roles: workflow-based roles (AR Specialist, Accountant, Treasury Analyst,
FP&A Analyst, Controller) and the Service POD workflows each person may work in

Revision ID: 7f3a2b9c4d51
Revises: 5e7a9c1d3b62
Create Date: 2026-11-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7f3a2b9c4d51'
down_revision: Union[str, Sequence[str], None] = '5e7a9c1d3b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLES = (
    "'finance_admin', 'ar_specialist', 'accountant', 'treasury_analyst', "
    "'fpa_analyst', 'controller', 'user'"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f('ck_users_user_role'), 'users', type_='check')
    op.create_check_constraint(op.f('ck_users_user_role'), 'users', f"role IN ({_ROLES})")
    op.add_column(
        'users',
        sa.Column(
            'pod_workflows',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'pod_workflows')
    # Anyone given a Service POD role becomes a plain user again
    op.execute("UPDATE users SET role = 'user' WHERE role NOT IN ('finance_admin', 'user')")
    op.drop_constraint(op.f('ck_users_user_role'), 'users', type_='check')
    op.create_check_constraint(
        op.f('ck_users_user_role'), 'users', "role IN ('finance_admin', 'user')"
    )
