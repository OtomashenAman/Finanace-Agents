"""period results

Revision ID: 460d3f354df2
Revises: 58dd28bca593
Create Date: 2026-10-21 14:03:07.453448

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '460d3f354df2'
down_revision: Union[str, Sequence[str], None] = '58dd28bca593'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_TYPES = (
    "vendor", "bill", "purchase_order", "account", "customer", "invoice", "payment", "expense",
    "account_balance", "subledger_total",
)
NEW_TYPES = (*OLD_TYPES, "period_result")


def _check(types: tuple[str, ...]) -> str:
    return "record_type IN ({})".format(", ".join(f"'{t}'" for t in types))


def upgrade() -> None:
    """Upgrade schema."""
    # The CHECK constraint lists the allowed record types (autogenerate doesn't see changes)
    op.drop_constraint(op.f("ck_finance_records_record_type"), "finance_records", type_="check")
    op.create_check_constraint("record_type", "finance_records", _check(NEW_TYPES))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM finance_records WHERE record_type = 'period_result'")
    op.drop_constraint(op.f("ck_finance_records_record_type"), "finance_records", type_="check")
    op.create_check_constraint("record_type", "finance_records", _check(OLD_TYPES))
