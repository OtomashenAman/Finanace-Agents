"""Read-only finance data for agents, always scoped to one user's own sources."""

import uuid
from datetime import date
from typing import TypeVar, cast

from sqlalchemy import ColumnElement, Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.data_sources.models import DataSource, FinanceRecord
from src.app.data_sources.records import RECORD_MODELS, Record, RecordType
from src.app.entities.models import LegalEntity

R = TypeVar("R", bound=Record)


def to_record(row: FinanceRecord) -> Record:
    return RECORD_MODELS[row.record_type].model_validate(row.data)


class FinanceData:
    """What an agent may read: the records of `owner_id`'s data sources.

    Lookups prefer `primary_source_id` (the source a run was prefilled from), then the sources
    linked to `entity_id` (the run's legal entity: its own books), then the most recently
    synced source, so a vendor master uploaded separately still applies.
    """

    def __init__(
        self,
        session: AsyncSession,
        owner_id: uuid.UUID,
        primary_source_id: uuid.UUID | None,
        entity_id: uuid.UUID | None = None,
        *,
        only_source: bool = False,
    ) -> None:
        self._session = session
        self.owner_id = owner_id
        self.primary_source_id = primary_source_id
        self.entity_id = entity_id
        # Read primary_source_id and nothing else (e.g. one entity's books, never another's)
        self.only_source = only_source

    def _preference(self) -> ColumnElement[int]:
        return case(
            (DataSource.id == self.primary_source_id, 0),
            (DataSource.entity_id == self.entity_id, 1),
            else_=2,
        )

    def _query(self, record_type: RecordType) -> Select[FinanceRecord]:
        preferred = self._preference()
        query = (
            select(FinanceRecord)
            .join(DataSource, DataSource.id == FinanceRecord.source_id)
            .where(DataSource.owner_id == self.owner_id, FinanceRecord.record_type == record_type)
            .order_by(preferred, DataSource.last_synced_at.desc().nulls_last())
        )
        if self.only_source:
            query = query.where(DataSource.id == self.primary_source_id)
        return query

    async def entity_aliases(self, entity: str) -> list[str]:
        """How a legal entity may be named in another entity's books: what was typed, plus
        its code and name when it matches a legal entity."""
        found = await self._session.scalar(
            select(LegalEntity).where(
                or_(
                    func.lower(LegalEntity.code) == entity.strip().lower(),
                    func.lower(LegalEntity.name) == entity.strip().lower(),
                )
            )
        )
        names = [entity.strip()] + ([found.code, found.name] if found else [])
        return list(dict.fromkeys(n for n in names if n))

    async def entity_books(self, entity: str) -> tuple["FinanceData", DataSource] | None:
        """The books of one legal entity (by code or name): the user's source linked to it,
        read on its own. None when no source is linked to that entity."""
        source = await self._session.scalar(
            select(DataSource)
            .join(LegalEntity, LegalEntity.id == DataSource.entity_id)
            .where(
                DataSource.owner_id == self.owner_id,
                or_(
                    func.lower(LegalEntity.code) == entity.strip().lower(),
                    func.lower(LegalEntity.name) == entity.strip().lower(),
                ),
            )
            .order_by(DataSource.last_synced_at.desc().nulls_last())
            .limit(1)
        )
        if source is None:
            return None
        books = FinanceData(
            self._session, self.owner_id, source.id, source.entity_id, only_source=True
        )
        return books, source

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

    async def find_all(
        self, record_type: RecordType, reference: str, limit: int = 5
    ) -> tuple[list[Record], DataSource | None]:
        """The records with this reference in the preferred source that has one, and that
        source. More than one (e.g. a payment reference used twice) means it's ambiguous."""
        first = await self._session.scalar(
            self._query(record_type).where(
                func.lower(FinanceRecord.reference) == reference.strip().lower()
            )
        )
        if first is None:
            return [], None
        rows = await self._session.scalars(
            select(FinanceRecord)
            .where(
                FinanceRecord.source_id == first.source_id,
                FinanceRecord.record_type == record_type,
                func.lower(FinanceRecord.reference) == reference.strip().lower(),
            )
            .order_by(FinanceRecord.external_id)
            .limit(limit)
        )
        source = await self._session.get(DataSource, first.source_id)
        return [to_record(row) for row in rows], source

    async def source_for(self, record_type: RecordType) -> DataSource | None:
        """The source records() reads this type from."""
        first = await self._session.scalar(self._query(record_type).limit(1))
        return await self._session.get(DataSource, first.source_id) if first else None

    async def latest_source(self) -> DataSource | None:
        """The run's own source, else its entity's, else the user's most recently synced one."""
        source: DataSource | None = await self._session.scalar(
            select(DataSource)
            .where(DataSource.owner_id == self.owner_id)
            .order_by(self._preference(), DataSource.last_synced_at.desc().nulls_last())
            .limit(1)
        )
        return source

    async def records(
        self, model: type[R], record_type: RecordType, counterparty: str | None = None
    ) -> list[R]:
        """Every record of this type from one source (the preferred one that has any),
        optionally only one counterparty's (case-insensitive), oldest first. One source
        only, so the same invoice in two sources is never counted twice."""
        first = await self._session.scalar(self._query(record_type).limit(1))
        if first is None:
            return []
        query = select(FinanceRecord).where(
            FinanceRecord.source_id == first.source_id, FinanceRecord.record_type == record_type
        )
        if counterparty is not None:
            query = query.where(
                func.lower(FinanceRecord.counterparty) == counterparty.strip().lower()
            )
        rows = await self._session.scalars(
            query.order_by(FinanceRecord.txn_date.nulls_last(), FinanceRecord.reference)
        )
        records = [to_record(row) for row in rows]
        assert all(isinstance(r, model) for r in records)  # noqa: S101 - record_type selects it
        return cast(list[R], records)

    async def books_closed_through(self) -> date | None:
        """The books closing date of the preferred source (QuickBooks only; uploads have none)."""
        preferred = self._preference()
        closed: date | None = await self._session.scalar(
            select(DataSource.books_closed_through)
            .where(DataSource.owner_id == self.owner_id)
            .order_by(preferred, DataSource.last_synced_at.desc().nulls_last())
            .limit(1)
        )
        return closed

    async def primary_source(self) -> DataSource | None:
        """The source the run is being prefilled from, if any."""
        if self.primary_source_id is None:
            return None
        return await self._session.get(DataSource, self.primary_source_id)
