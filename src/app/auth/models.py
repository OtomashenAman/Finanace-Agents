import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.default import DefaultExecutionContext
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


class Area(StrEnum):
    """The parts of the app a Finance Admin gives each person (the nav shows only these)."""

    AGENT_CATALOG = "agent_catalog"
    SERVICE_POD = "service_pod"  # Finance Admins only
    FINANCE_POD = "finance_pod"  # Finance Admins only


ADMIN_ONLY_AREAS = frozenset({Area.SERVICE_POD, Area.FINANCE_POD})


def default_areas(role: UserRole) -> list[Area]:
    """What a new account gets unless the admin picks: everything its role allows."""
    return [a for a in Area if role == UserRole.FINANCE_ADMIN or a not in ADMIN_ONLY_AREAS]


def _areas_for_new_row(context: DefaultExecutionContext) -> list[str]:
    role = context.get_current_parameters()["role"]  # type: ignore[no-untyped-call]
    return [a.value for a in default_areas(UserRole(role))]


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
    # Area values; Service POD and Finance POD only ever for a Finance Admin
    areas: Mapped[list[str]] = mapped_column(
        JSONB,
        default=_areas_for_new_row,
        server_default=text("""'["agent_catalog", "service_pod", "finance_pod"]'::jsonb"""),
    )

    def can_use(self, area: Area) -> bool:
        if area in ADMIN_ONLY_AREAS and self.role != UserRole.FINANCE_ADMIN:
            return False
        return area.value in self.areas


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
