"""The lab system's side of a client account.

Today's pain: a client is set up twice, once in the ERP and again in the lab system. The
account agent writes both from one approved record, and the monitor checks they still
agree. There is no lab system (LIMS) connection yet, so the Finance POD keeps the lab's
client register itself (fpod_lab_clients); a real LIMS connector replaces LocalLab behind
the same two calls.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.finance_pod.clients.models import FpLabClient


@dataclass(frozen=True)
class LabRecord:
    client_code: str
    name: str
    billing_email: str
    currency: str
    work_status: str  # credit / deposit / hold
    credit_limit: Decimal | None
    deposit_pct: Decimal


class LabSystem(Protocol):
    name: str

    async def upsert_client(self, session: AsyncSession, record: LabRecord) -> str:
        """The lab system's reference for the client (created, or updated in place)."""
        ...

    async def read_client(self, session: AsyncSession, client_code: str) -> LabRecord | None:
        """What the lab system holds for the client now."""
        ...


class LocalLab:
    name = "local"

    async def upsert_client(self, session: AsyncSession, record: LabRecord) -> str:
        row = await session.scalar(
            select(FpLabClient).where(FpLabClient.client_code == record.client_code)
        )
        if row is None:
            row = FpLabClient(lab_code=f"LAB-{record.client_code}", client_code=record.client_code)
            session.add(row)
        row.name, row.billing_email, row.currency = (
            record.name,
            record.billing_email,
            record.currency,
        )
        row.work_status, row.credit_limit = record.work_status, record.credit_limit
        row.deposit_pct = record.deposit_pct
        await session.flush()
        return row.lab_code

    async def read_client(self, session: AsyncSession, client_code: str) -> LabRecord | None:
        row = await session.scalar(
            select(FpLabClient).where(FpLabClient.client_code == client_code)
        )
        if row is None:
            return None
        return LabRecord(
            client_code=row.client_code,
            name=row.name,
            billing_email=row.billing_email,
            currency=row.currency,
            work_status=row.work_status,
            credit_limit=row.credit_limit,
            deposit_pct=row.deposit_pct,
        )


def get_lab() -> LabSystem:
    return LocalLab()
