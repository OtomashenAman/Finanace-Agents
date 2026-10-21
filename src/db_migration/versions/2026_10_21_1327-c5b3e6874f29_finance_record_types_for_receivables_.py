"""finance record types for receivables and expenses

Revision ID: c5b3e6874f29
Revises: c783154db3aa
Create Date: 2026-10-21 13:27:22.316019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5b3e6874f29'
down_revision: Union[str, Sequence[str], None] = 'c783154db3aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_TYPES = ("vendor", "bill", "purchase_order", "account")
NEW_TYPES = (*OLD_TYPES, "customer", "invoice", "payment", "expense")


def _check(types: tuple[str, ...]) -> str:
    return "record_type IN ({})".format(", ".join(f"'{t}'" for t in types))


def upgrade() -> None:
    """Upgrade schema."""
    # The CHECK constraint lists the allowed record types (autogenerate doesn't see changes)
    op.drop_constraint(op.f("ck_finance_records_record_type"), "finance_records", type_="check")
    op.create_check_constraint("record_type", "finance_records", _check(NEW_TYPES))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM finance_records WHERE record_type IN ('customer', 'invoice', 'payment', 'expense')"
    )
    op.drop_constraint(op.f("ck_finance_records_record_type"), "finance_records", type_="check")
    op.create_check_constraint("record_type", "finance_records", _check(OLD_TYPES))
