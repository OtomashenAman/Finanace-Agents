import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so Alembic migrations stay stable
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012 - SQLAlchemy config


def string_enum(enum_cls: type[StrEnum], length: int) -> Enum:
    """VARCHAR column type for a StrEnum (no native PG enum: new values need no ALTER TYPE).

    Pair it with enum_check() in __table_args__. Enum(create_constraint=True) is avoided on
    purpose: Alembic autogenerate renders its CHECK twice and the migration fails.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda members: [m.value for m in members],
    )


def enum_check(column: str, enum_cls: type[StrEnum], name: str | None = None) -> CheckConstraint:
    """CHECK (column IN (...)), named ck_<table>_<name or column> by the naming convention."""
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=name or column)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
