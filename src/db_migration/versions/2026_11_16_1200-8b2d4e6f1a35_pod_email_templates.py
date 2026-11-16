"""pod email templates: a customer's own email format (one per customer of a company and
workflow), used for every new draft to that customer

Revision ID: 8b2d4e6f1a35
Revises: 3c8e1f2a9d47
Create Date: 2026-11-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8b2d4e6f1a35'
down_revision: Union[str, Sequence[str], None] = '3c8e1f2a9d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'pod_email_templates',
        sa.Column('workflow', sa.String(length=40), nullable=False),
        sa.Column('company_id', sa.String(length=100), nullable=False),
        sa.Column('customer_id', sa.String(length=100), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_pod_email_templates_updated_by_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pod_email_templates')),
        sa.UniqueConstraint('workflow', 'company_id', 'customer_id', name=op.f('uq_pod_email_templates_workflow')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('pod_email_templates')
