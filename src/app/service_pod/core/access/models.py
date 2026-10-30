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
from src.app.service_pod.core.workflows import Capacity, WorkflowKey


class PodAssignment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """What a user may do in one Service POD workflow. Checked live on every request, so a
    change applies at once without signing anyone out."""

    __tablename__ = "pod_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "workflow", "capacity"),
        enum_check("workflow", WorkflowKey),
        enum_check("capacity", Capacity),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    workflow: Mapped[WorkflowKey] = mapped_column(string_enum(WorkflowKey, 32))
    capacity: Mapped[Capacity] = mapped_column(string_enum(Capacity, 32))
