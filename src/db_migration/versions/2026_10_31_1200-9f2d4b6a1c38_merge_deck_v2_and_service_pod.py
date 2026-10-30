"""merge the deck v2 and Service POD migration chains

Both branched from 13ef2333c624; this joins their heads so `alembic upgrade head` has one
target. No schema change of its own.

Revision ID: 9f2d4b6a1c38
Revises: 4a9c3e7f1b28, 8b3f6c1d9e20
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = '9f2d4b6a1c38'
down_revision: Union[str, Sequence[str], None] = ('4a9c3e7f1b28', '8b3f6c1d9e20')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
