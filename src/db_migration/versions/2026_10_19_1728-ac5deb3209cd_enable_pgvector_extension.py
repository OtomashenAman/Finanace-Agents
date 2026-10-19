"""enable pgvector extension

Revision ID: ac5deb3209cd
Revises:
Create Date: 2026-10-19 17:28:12.828437

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac5deb3209cd"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable pgvector (needs CREATE privilege on the database; managed Postgres may need an admin)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
