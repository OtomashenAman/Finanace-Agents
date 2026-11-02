import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)
from src.app.service_pod.core.steps.spec import StepStatus


class PodCaseStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One L5 step of one case: pending until a person or the agent settles it. Created
    for every L5 the workflow declares when the case opens, so nothing can be skipped
    silently: a step that doesn't apply is not_applicable with its reason in `note`."""

    __tablename__ = "pod_case_steps"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("case_id", "l5_code"),
        enum_check("status", StepStatus),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(32))
    l5_code: Mapped[str] = mapped_column(String(32))
    status: Mapped[StepStatus] = mapped_column(
        string_enum(StepStatus, 16), default=StepStatus.PENDING
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    done_by: Mapped[uuid.UUID | None] = mapped_column(  # None: the agent or the system
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    done_at: Mapped[datetime | None]
