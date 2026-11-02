import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)
from src.app.finance_pod.capacities import FinanceCapacity


class FinanceCapacityAssignment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A Finance Admin granted someone a capacity, for one legal entity or (entity_id None)
    for all of them. Revoking deletes the row; both are audited."""

    __tablename__ = "finance_capacity_assignments"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("user_id", "capacity", "entity_id", postgresql_nulls_not_distinct=True),
        enum_check("capacity", FinanceCapacity),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    capacity: Mapped[FinanceCapacity] = mapped_column(string_enum(FinanceCapacity, 32))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE")
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
