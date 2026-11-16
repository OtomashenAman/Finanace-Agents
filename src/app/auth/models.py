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
    FINANCE_ADMIN = "finance_admin"  # every workflow, every sign-off, user management, settings
    # Service POD roles: they prepare the work of the workflows they're given; a Finance
    # Admin signs it off. Each role starts with ROLE_WORKFLOWS[role]; the admin can adjust.
    AR_SPECIALIST = "ar_specialist"
    ACCOUNTANT = "accountant"
    TREASURY_ANALYST = "treasury_analyst"
    FPA_ANALYST = "fpa_analyst"
    CONTROLLER = "controller"
    USER = "user"  # no workflows by default: only what an admin assigns


# Service POD workflow keys (service_pod.core.workflows.WorkflowKey values; kept as strings
# here so auth doesn't import the Service POD)
POD_WORKFLOWS = ("ar_collections", "bank_recon", "fpa_trend", "treasury", "reporting")

ROLE_WORKFLOWS: dict[UserRole, tuple[str, ...]] = {
    UserRole.FINANCE_ADMIN: POD_WORKFLOWS,
    UserRole.AR_SPECIALIST: ("ar_collections",),
    UserRole.ACCOUNTANT: ("bank_recon",),
    UserRole.TREASURY_ANALYST: ("treasury",),
    UserRole.FPA_ANALYST: ("fpa_trend",),
    UserRole.CONTROLLER: ("reporting", "bank_recon", "ar_collections"),
    UserRole.USER: (),
}


def default_pod_workflows(role: UserRole) -> list[str]:
    """The Service POD workflows a new account gets unless the admin picks."""
    return list(ROLE_WORKFLOWS[role])


class Area(StrEnum):
    """The parts of the app a Finance Admin gives each person (the nav shows only these)."""

    AGENT_CATALOG = "agent_catalog"
    SERVICE_POD = "service_pod"  # everyone, limited to their pod_workflows
    FINANCE_POD = "finance_pod"  # Finance Admins only


ADMIN_ONLY_AREAS = frozenset({Area.FINANCE_POD})


def default_areas(role: UserRole) -> list[Area]:
    """What a new account gets unless the admin picks: everything its role allows."""
    return [a for a in Area if role == UserRole.FINANCE_ADMIN or a not in ADMIN_ONLY_AREAS]


def _areas_for_new_row(context: DefaultExecutionContext) -> list[str]:
    role = context.get_current_parameters()["role"]  # type: ignore[no-untyped-call]
    return [a.value for a in default_areas(UserRole(role))]


def _workflows_for_new_row(context: DefaultExecutionContext) -> list[str]:
    role = context.get_current_parameters()["role"]  # type: ignore[no-untyped-call]
    return default_pod_workflows(UserRole(role))


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
    # Area values; Finance POD only ever for a Finance Admin
    areas: Mapped[list[str]] = mapped_column(
        JSONB,
        default=_areas_for_new_row,
        server_default=text("""'["agent_catalog", "service_pod", "finance_pod"]'::jsonb"""),
    )

    # Service POD workflows they may work in (a Finance Admin always has every one)
    pod_workflows: Mapped[list[str]] = mapped_column(
        JSONB, default=_workflows_for_new_row, server_default=text("'[]'::jsonb")
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.FINANCE_ADMIN

    def workflows(self) -> list[str]:
        """The Service POD workflows this person may work in, in the POD's order."""
        if self.is_admin:
            return list(POD_WORKFLOWS)
        return [w for w in POD_WORKFLOWS if w in (self.pod_workflows or [])]

    @property
    def workflow_keys(self) -> list[str]:
        """workflows() as an attribute (for UserOut)."""
        return self.workflows()

    def can_use(self, area: Area) -> bool:
        if area in ADMIN_ONLY_AREAS and not self.is_admin:
            return False
        if area == Area.SERVICE_POD and not self.workflows():
            return False  # nothing to work on there
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
