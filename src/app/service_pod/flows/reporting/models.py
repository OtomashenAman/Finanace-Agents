"""A management pack as it was approved: the PDF bytes are stored once and never changed."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class PodReportPack(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One exported pack (TDD: immutable PDF bytes, source hash, content hash, reviewer
    records and timestamps). Editing the case afterwards leaves it as history: a pack is
    current only while its content_hash equals the case's fingerprint."""

    __tablename__ = "pod_report_packs"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (UniqueConstraint("case_id", "number"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int]  # 1, 2, ... per case
    content_hash: Mapped[str] = mapped_column(String(64))  # the approvals' fingerprint
    source_sha: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))  # of the PDF bytes, checked on retrieval
    size: Mapped[int]
    reviewers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # capacity, name, at
    pdf: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    # The same bytes as an approved case document, so a message can attach them
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_artifacts.id", ondelete="RESTRICT")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
