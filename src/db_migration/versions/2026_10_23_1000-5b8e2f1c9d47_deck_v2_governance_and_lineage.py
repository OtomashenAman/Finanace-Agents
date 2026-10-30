"""deck v2: narrative lineage, maker-checker by default

Revision ID: 5b8e2f1c9d47
Revises: 13ef2333c624
Create Date: 2026-10-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b8e2f1c9d47'
down_revision: Union[str, Sequence[str], None] = '13ef2333c624'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('run_narratives', sa.Column('prompt_hash', sa.String(length=64), nullable=True))
    op.add_column('run_narratives', sa.Column('policy_version', sa.String(length=100), nullable=True))
    # Maker and checker are different people unless a Finance Admin turns self-approval on.
    # An existing choice (a row already saved) is kept.
    op.alter_column('org_settings', 'allow_admin_self_approval', server_default=sa.text('false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('org_settings', 'allow_admin_self_approval', server_default=sa.text('true'))
    op.drop_column('run_narratives', 'policy_version')
    op.drop_column('run_narratives', 'prompt_hash')
