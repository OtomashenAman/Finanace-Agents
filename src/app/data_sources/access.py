"""Read-only finance data for agents, always scoped to one user's own sources."""

import uuid
from typing import TypeVar

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.data_sources.models import DataSource, FinanceRecord
from src.app.data_sources.records import RECORD_MODELS, Record, RecordType

R = TypeVar("R", bound=Record)


def to_record(row: FinanceRecord) -> Record:
    return RECORD_MODELS[row.record_type].model_validate(row.data)


class FinanceData:
    """What an agent may read: the records of `owner_id`'s data sources.

    Lookups prefer `primary_source_id` (the source a run was prefilled from), then the most
    recently synced source, so a vendor master uploaded separately still applies.
    """

    def __init__(
        self, session: AsyncSession, owner_id: uuid.UUID, primary_source_id: uuid.UUID | None
    ) -> None:
        self._session = session
        self.owner_id = owner_id
        self.primary_source_id = primary_source_id

    def _query(self, record_type: RecordType) -> Select[FinanceRecord]:
        preferred = case((FinanceRecord.source_id == self.primary_source_id, 0), else_=1)
        return (
            select(FinanceRecord)
            .join(DataSource, DataSource.id == FinanceRecord.source_id)
            .where(DataSource.owner_id == self.owner_id, FinanceRecord.record_type == record_type)
            .order_by(preferred, DataSource.last_synced_at.desc().nulls_last())
        )

    async def has(self, record_type: RecordType) -> bool:
        """Whether the user has any records of this type (e.g. a vendor master to check)."""
        found = await self._session.scalar(self._query(record_type).limit(1))
        return found is not None

    async def find(self, model: type[R], record_type: RecordType, reference: str) -> R | None:
        """Exact, case-insensitive match on the record's reference (name, doc number...)."""
        row = await self._session.scalar(
            self._query(record_type)
            .where(func.lower(FinanceRecord.reference) == reference.strip().lower())
            .limit(1)
        )
        if row is None:
            return None
        record = to_record(row)
        assert isinstance(record, model)  # noqa: S101 - record_type selects the model
        return record
