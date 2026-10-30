"""data source legal entity: one QuickBooks company per entity

Revision ID: 8c3d1a7e4f20
Revises: 5b8e2f1c9d47
Create Date: 2026-10-23 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c3d1a7e4f20'
down_revision: Union[str, Sequence[str], None] = '5b8e2f1c9d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('data_sources', sa.Column('entity_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_data_sources_entity_id'), 'data_sources', ['entity_id'], unique=False)
    op.create_foreign_key(
        op.f('fk_data_sources_entity_id_legal_entities'),
        'data_sources', 'legal_entities', ['entity_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f('fk_data_sources_entity_id_legal_entities'), 'data_sources', type_='foreignkey'
    )
    op.drop_index(op.f('ix_data_sources_entity_id'), table_name='data_sources')
    op.drop_column('data_sources', 'entity_id')
