"""service pod report packs: the management pack PDFs, stored immutably

Each export of a Controller- and CFO-approved Financial Reporting case: the PDF bytes, their
SHA-256 (checked on every read), the source and content hashes and the reviewers.

Revision ID: c3d9a1e7f2b4
Revises: a4c7e2f9b1d3
Create Date: 2026-11-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d9a1e7f2b4'
down_revision: Union[str, Sequence[str], None] = 'a4c7e2f9b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('pod_report_packs',
    sa.Column('case_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('source_sha', sa.String(length=64), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('reviewers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('pdf', sa.LargeBinary(), nullable=False),
    sa.Column('artifact_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['pod_artifacts.id'], name=op.f('fk_pod_report_packs_artifact_id_pod_artifacts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['case_id'], ['pod_cases.id'], name=op.f('fk_pod_report_packs_case_id_pod_cases'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_pod_report_packs_created_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pod_report_packs')),
    sa.UniqueConstraint('case_id', 'number', name=op.f('uq_pod_report_packs_case_id'))
    )
    op.create_index(op.f('ix_pod_report_packs_case_id'), 'pod_report_packs', ['case_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_pod_report_packs_case_id'), table_name='pod_report_packs')
    op.drop_table('pod_report_packs')
