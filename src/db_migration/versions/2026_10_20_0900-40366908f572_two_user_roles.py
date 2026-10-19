"""two user roles: finance_admin and user

Revision ID: 40366908f572
Revises: 6604e43909ea
Create Date: 2026-10-20 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '40366908f572'
down_revision: Union[str, Sequence[str], None] = '6604e43909ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # preparer/reviewer were only labels; per-agent capacities live in agent_assignments
    op.drop_constraint(op.f('ck_users_user_role'), 'users', type_='check')
    op.execute("UPDATE users SET role = 'user' WHERE role IN ('preparer', 'reviewer')")
    op.create_check_constraint(op.f('ck_users_user_role'), 'users', "role IN ('finance_admin', 'user')")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('ck_users_user_role'), 'users', type_='check')
    op.execute("UPDATE users SET role = 'preparer' WHERE role = 'user'")
    op.create_check_constraint(
        op.f('ck_users_user_role'), 'users', "role IN ('finance_admin', 'preparer', 'reviewer')"
    )
