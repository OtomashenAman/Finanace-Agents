import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)


class TaskKind(StrEnum):
    RECEIVE_PAYMENT = "receive_payment"  # apply a cleared receipt to invoices
    JOURNAL_ENTRY = "journal_entry"  # an approved correction
    # Finance POD: the app posts these to the ERP when a person approves it (post action)
    CREATE_SUPPLIER = "create_supplier"
    CREATE_PURCHASE_ORDER = "create_purchase_order"
    CREATE_PURCHASE_RECEIPT = "create_purchase_receipt"  # a receiver confirmed the delivery
    CREATE_JOURNAL_ENTRY = "create_journal_entry"  # e.g. a month-end accrual and its reversal
    CREATE_CUSTOMER = "create_customer"  # a client account with its approved credit terms


class TaskStatus(StrEnum):
    PROPOSED = "proposed"  # the Finance Admin posts it in QuickBooks
    RECORDED_UNVERIFIED = "recorded_unverified"  # posted outside, transaction ID noted
    VERIFIED = "verified"  # a fresh snapshot proves the posting
    CANCELLED = "cancelled"


class PodPostingTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Accounting a person performs in QuickBooks; the application never posts. Recording a
    transaction ID isn't verification: only a later, different snapshot of the same company
    that contains the posting is."""

    __tablename__ = "pod_posting_tasks"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("kind", TaskKind), enum_check("status", TaskStatus))

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_cases.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[TaskKind] = mapped_column(string_enum(TaskKind, 32))
    # Hash of company, entity, kind and reference: the same posting can't be queued twice
    task_key: Mapped[str] = mapped_column(String(64), unique=True)
    reference: Mapped[str] = mapped_column(String(100))  # e.g. the bank reference
    status: Mapped[TaskStatus] = mapped_column(string_enum(TaskStatus, 32), index=True)
    version: Mapped[int] = mapped_column(default=1)
    instructions: Mapped[dict[str, Any]] = mapped_column(JSONB)  # what to post
    note: Mapped[str | None] = mapped_column(Text)

    proposed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    external_txn_id: Mapped[str | None] = mapped_column(String(100))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    recorded_at: Mapped[datetime | None]
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    verified_at: Mapped[datetime | None]
    verification_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pod_snapshots.id", ondelete="RESTRICT")
    )
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # the checks and results
