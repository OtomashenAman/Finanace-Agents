"""deck v2 agent inputs: daily cash low, revenue to date, comparison period, metric, basis

Revision ID: 2f6a9b0d3e51
Revises: 8c3d1a7e4f20
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f6a9b0d3e51'
down_revision: Union[str, Sequence[str], None] = '8c3d1a7e4f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(precision=18, scale=2)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('treasury_cash_runs', sa.Column('lowest_projected_cash', MONEY, nullable=True))
    op.add_column('treasury_cash_runs', sa.Column('lowest_cash_date', sa.String(length=10), nullable=True))
    op.add_column('revenue_recognition_runs', sa.Column('months_delivered', sa.Integer(), nullable=True))
    op.add_column('revenue_recognition_runs', sa.Column('earned_to_date', MONEY, nullable=True))
    op.add_column('revenue_recognition_runs', sa.Column('deferred_revenue', MONEY, nullable=True))
    op.add_column('board_reporting_runs', sa.Column('comparison_period', sa.String(length=20), nullable=True))
    op.add_column('fpa_forecast_runs', sa.Column('metric', sa.String(length=30), nullable=True))
    op.add_column('financial_close_runs', sa.Column('accounting_basis', sa.String(length=10), nullable=True))
    op.add_column('financial_close_runs', sa.Column('currency', sa.String(length=3), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('financial_close_runs', 'currency')
    op.drop_column('financial_close_runs', 'accounting_basis')
    op.drop_column('fpa_forecast_runs', 'metric')
    op.drop_column('board_reporting_runs', 'comparison_period')
    op.drop_column('revenue_recognition_runs', 'deferred_revenue')
    op.drop_column('revenue_recognition_runs', 'earned_to_date')
    op.drop_column('revenue_recognition_runs', 'months_delivered')
    op.drop_column('treasury_cash_runs', 'lowest_cash_date')
    op.drop_column('treasury_cash_runs', 'lowest_projected_cash')
