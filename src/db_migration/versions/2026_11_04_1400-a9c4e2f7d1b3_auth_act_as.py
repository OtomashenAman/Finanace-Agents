"""auth act as: a Finance Admin's session as another user

refresh_tokens.acted_by_id: the admin testing a workflow as the token's user.

Revision ID: a9c4e2f7d1b3
Revises: f3b8d2a6c1e4
Create Date: 2026-11-04 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a9c4e2f7d1b3'
down_revision: Union[str, Sequence[str], None] = 'f3b8d2a6c1e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("acted_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_refresh_tokens_acted_by_id_users"), "refresh_tokens", "users",
        ["acted_by_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_refresh_tokens_acted_by_id_users"), "refresh_tokens",
                       type_="foreignkey")
    op.drop_column("refresh_tokens", "acted_by_id")
