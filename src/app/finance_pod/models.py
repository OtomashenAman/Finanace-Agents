import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
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


class SanctionsLoad(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One download of a sanctions list (the OFAC SDN list): its entries replace the last
    load's. Screening says which load it used, so an old answer can be traced."""

    __tablename__ = "finance_sanctions_loads"

    list_name: Mapped[str] = mapped_column(String(50))  # "OFAC SDN"
    source_url: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    entries: Mapped[int]


class SanctionsEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "finance_sanctions_entries"

    load_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finance_sanctions_loads.id", ondelete="CASCADE"), index=True
    )
    entry_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(500))
    normalized: Mapped[str] = mapped_column(String(500), index=True)  # for matching
    entity_type: Mapped[str | None] = mapped_column(String(50))
    programs: Mapped[str | None] = mapped_column(String(500))
