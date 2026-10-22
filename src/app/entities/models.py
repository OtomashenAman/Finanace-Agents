import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LegalEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A legal entity runs are filed for (e.g. "US01 · US Operations").

    Finance Admins manage them and choose which entities each user works for. Deactivated
    entities keep their runs but take no new ones; they are never deleted.
    """

    __tablename__ = "legal_entities"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    code: Mapped[str] = mapped_column(String(20), unique=True)  # stored uppercase
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))


class EntityAssignment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Which legal entities a user may file runs for and see runs of."""

    __tablename__ = "entity_assignments"
    __table_args__ = (UniqueConstraint("user_id", "entity_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="CASCADE"), index=True
    )
