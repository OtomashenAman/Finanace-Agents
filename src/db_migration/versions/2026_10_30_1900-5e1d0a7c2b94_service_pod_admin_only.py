"""service pod admin only: no roles, one approval step

The Finance Admin runs the Service POD alone: role assignments go, a case is approved in
one step (draft -> approved), a message is approved as it is sent, and a manual posting is
recorded without a separate approval.

Revision ID: 5e1d0a7c2b94
Revises: c962ad3ce6b8
Create Date: 2026-10-30 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e1d0a7c2b94'
down_revision: Union[str, Sequence[str], None] = 'c962ad3ce6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _status_check(table: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(f'ck_{table}_status'), table, type_='check')
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(f'ck_{table}_status'), table, f"status IN ({allowed})")


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f('ix_pod_assignments_user_id'), table_name='pod_assignments')
    op.drop_table('pod_assignments')

    # Cases: cases waiting on a reviewer are drafts again; a rejected case is cancelled
    op.execute(
        "UPDATE pod_cases SET status = 'draft' "
        "WHERE status IN ('in_review', 'awaiting_final', 'changes_requested')"
    )
    op.execute("UPDATE pod_cases SET status = 'cancelled' WHERE status = 'rejected'")
    _status_check('pod_cases', ('draft', 'approved', 'completed', 'cancelled'))
    op.drop_column('pod_cases', 'stage')

    # Approvals: only approvals remain, without a gate or a decision
    op.execute("DELETE FROM pod_approvals WHERE decision <> 'approved' OR gate <> 'review'")
    for column in ('gate', 'decision', 'policy_version', 'comment'):
        op.drop_column('pod_approvals', column)

    # Messages: an approved, unsent message is a draft again (it's approved as it is sent)
    op.execute(
        "UPDATE pod_messages SET status = 'draft', approval_hash = NULL, approved_by = NULL, "
        "approved_at = NULL, approval_checks = NULL, provider = NULL, sender = NULL "
        "WHERE status = 'approved'"
    )
    _status_check(
        'pod_messages', ('draft', 'sending', 'sent', 'send_failed', 'send_unknown', 'received')
    )

    # Posting tasks: proposed -> recorded_unverified -> verified
    op.execute("UPDATE pod_posting_tasks SET status = 'proposed' WHERE status = 'approved'")
    _status_check('pod_posting_tasks', ('proposed', 'recorded_unverified', 'verified', 'cancelled'))
    op.drop_constraint(
        op.f('fk_pod_posting_tasks_approved_by_users'), 'pod_posting_tasks', type_='foreignkey'
    )
    op.drop_column('pod_posting_tasks', 'approved_by')
    op.drop_column('pod_posting_tasks', 'approved_at')


def downgrade() -> None:
    """Downgrade schema (the structure comes back; dropped assignments and decisions don't)."""
    op.add_column('pod_posting_tasks', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('pod_posting_tasks', sa.Column('approved_by', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f('fk_pod_posting_tasks_approved_by_users'), 'pod_posting_tasks', 'users',
        ['approved_by'], ['id'], ondelete='RESTRICT',
    )
    _status_check(
        'pod_posting_tasks', ('proposed', 'approved', 'recorded_unverified', 'verified', 'cancelled')
    )
    _status_check(
        'pod_messages',
        ('draft', 'approved', 'sending', 'sent', 'send_failed', 'send_unknown', 'received'),
    )

    op.add_column('pod_approvals', sa.Column('comment', sa.Text(), nullable=True))
    op.add_column('pod_approvals', sa.Column('policy_version', sa.String(length=50), nullable=True))
    op.add_column(
        'pod_approvals',
        sa.Column('decision', sa.String(length=32), nullable=False, server_default='approved'),
    )
    op.add_column(
        'pod_approvals', sa.Column('gate', sa.String(length=16), nullable=False, server_default='review')
    )
    op.create_check_constraint(
        op.f('ck_pod_approvals_decision'), 'pod_approvals',
        "decision IN ('approved', 'changes_requested', 'rejected')",
    )
    op.create_check_constraint(op.f('ck_pod_approvals_gate'), 'pod_approvals', "gate IN ('review', 'final')")

    op.add_column(
        'pod_cases', sa.Column('stage', sa.String(length=50), nullable=False, server_default='start')
    )
    _status_check(
        'pod_cases',
        ('draft', 'in_review', 'awaiting_final', 'approved', 'changes_requested', 'rejected',
         'completed', 'cancelled'),
    )

    op.create_table('pod_assignments',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('workflow', sa.Enum('ar_collections', 'bank_recon', 'fpa_trend', 'treasury', 'reporting', name='workflowkey', native_enum=False, length=32), nullable=False),
    sa.Column('capacity', sa.Enum('preparer', 'reviewer', 'final_approver', 'poster', name='capacity', native_enum=False, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("capacity IN ('preparer', 'reviewer', 'final_approver', 'poster')", name=op.f('ck_pod_assignments_capacity')),
    sa.CheckConstraint("workflow IN ('ar_collections', 'bank_recon', 'fpa_trend', 'treasury', 'reporting')", name=op.f('ck_pod_assignments_workflow')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_pod_assignments_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pod_assignments')),
    sa.UniqueConstraint('user_id', 'workflow', 'capacity', name=op.f('uq_pod_assignments_user_id'))
    )
    op.create_index(op.f('ix_pod_assignments_user_id'), 'pod_assignments', ['user_id'], unique=False)
