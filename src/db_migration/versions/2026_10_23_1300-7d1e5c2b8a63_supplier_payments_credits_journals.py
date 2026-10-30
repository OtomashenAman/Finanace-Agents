"""finance record types: supplier payments, credit memos, supplier credits, journal lines;
SOX population period and threshold

Revision ID: 7d1e5c2b8a63
Revises: 2f6a9b0d3e51
Create Date: 2026-10-23 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d1e5c2b8a63'
down_revision: Union[str, Sequence[str], None] = '2f6a9b0d3e51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_TYPES = (
    "vendor", "bill", "purchase_order", "account", "customer", "invoice", "payment", "expense",
    "account_balance", "subledger_total", "period_result",
)
ADDED = ("bill_payment", "credit_memo", "vendor_credit", "journal_line")
NEW_TYPES = (*OLD_TYPES, *ADDED)


def _check(types: tuple[str, ...]) -> str:
    return "record_type IN ({})".format(", ".join(f"'{t}'" for t in types))


def upgrade() -> None:
    """Upgrade schema."""
    # The CHECK constraint lists the allowed record types (autogenerate doesn't see changes)
    op.drop_constraint(op.f("ck_finance_records_record_type"), "finance_records", type_="check")
    op.create_check_constraint("record_type", "finance_records", _check(NEW_TYPES))
    op.add_column('sox_controls_runs', sa.Column('test_period', sa.String(length=20), nullable=True))
    op.add_column(
        'sox_controls_runs',
        sa.Column('population_threshold', sa.Numeric(precision=18, scale=2), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sox_controls_runs', 'population_threshold')
    op.drop_column('sox_controls_runs', 'test_period')
    op.execute(
        "DELETE FROM finance_records WHERE record_type IN ({})".format(
            ", ".join(f"'{t}'" for t in ADDED)
        )
    )
    op.drop_constraint(op.f("ck_finance_records_record_type"), "finance_records", type_="check")
    op.create_check_constraint("record_type", "finance_records", _check(OLD_TYPES))
