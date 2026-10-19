import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(StrEnum):
    FINANCE_ADMIN = "finance_admin"
    PREPARER = "preparer"
    REVIEWER = "reviewer"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    # load server defaults (timestamps) after INSERT
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    email: Mapped[str] = mapped_column(String(320), unique=True)  # always stored lowercase
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(
        # VARCHAR + CHECK instead of a native enum: adding roles later needs no ALTER TYPE
        Enum(
            UserRole,
            name="user_role",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda roles: [r.value for r in roles],
        )
    )
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    failed_login_attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]


class RefreshToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One row per issued refresh token. Rotated on every refresh; the raw token is never stored."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # All tokens rotated from one login share a family; reuse of a revoked token kills the family
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[str | None] = mapped_column(String(45))
