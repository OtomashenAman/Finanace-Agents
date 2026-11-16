"""service pod for everyone: accounts made while the Service POD was admin-only get the
area, so the workflows an admin gives them show up (the areas editor is hidden for now)

Revision ID: 9c4d2e7f8a16
Revises: 7f3a2b9c4d51
Create Date: 2026-11-17 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9c4d2e7f8a16'
down_revision: Union[str, Sequence[str], None] = '7f3a2b9c4d51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Non-admins could never have had it, so no one loses a deliberate choice. Without a
    # workflow they still don't see the Service POD (User.can_use).
    op.execute(
        """
        UPDATE users SET areas = areas || '["service_pod"]'::jsonb
        WHERE role <> 'finance_admin' AND NOT (areas @> '["service_pod"]'::jsonb)
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The Service POD was admin-only before
    op.execute(
        """
        UPDATE users SET areas = areas - 'service_pod'
        WHERE role <> 'finance_admin'
        """
    )
