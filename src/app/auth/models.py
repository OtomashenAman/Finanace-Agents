import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class UserRole(StrEnum):
    FINANCE_ADMIN = "finance_admin"  # every agent, user management, settings
    USER = "user"  # only the agents (and capacities) an admin assigns


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", UserRole, name="user_role"),)  # ck_users_user_role
    # load server defaults (timestamps) after INSERT
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    email: Mapped[str] = mapped_column(String(320), unique=True)  # always stored lowercase
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(string_enum(UserRole, 32))
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


class PasswordResetRequest(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """ "Forgot password": waits in the Finance Admins' worklist until one sets a new password."""

    __tablename__ = "password_reset_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ip: Mapped[str | None] = mapped_column(String(45))
    resolved_at: Mapped[datetime | None]
