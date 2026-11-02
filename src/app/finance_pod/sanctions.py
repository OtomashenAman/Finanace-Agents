"""The OFAC Specially Designated Nationals (SDN) list: downloaded by a daily job (or an
admin), each load replacing the last, and the screening that matches names against it.

Screening is fuzzy (normalized names, a similarity threshold): a hit is a blocking review
task for a person to clear, never an automatic refusal and never silently ignored. With no
list loaded, screening refuses to say anything.
"""

import csv
import difflib
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import get_settings
from src.app.finance_pod.models import SanctionsEntry, SanctionsLoad
from src.app.jobs import queue as jobs
from src.app.jobs.queue import JobContext

LIST_NAME = "OFAC SDN"
JOB = "finance.sanctions_refresh"
transport: httpx.AsyncBaseTransport | None = None  # tests swap in an httpx.MockTransport

_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|co|corp|corporation|company|gmbh|sa|plc|lp|llp)\b"
)


def normalize(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    return re.sub(r"\s+", " ", _SUFFIXES.sub(" ", text)).strip()


def parse_sdn(data: bytes) -> list[dict[str, str | None]]:
    """OFAC's SDN.CSV: no header; ent_num, SDN_Name, SDN_Type, Program, ... (-0- = empty)."""
    rows = []
    for row in csv.reader(io.StringIO(data.decode("latin-1"))):
        if len(row) < 4 or not row[0].strip().isdigit():
            continue

        def clean(v: str) -> str | None:
            v = v.strip()
            return None if v in ("", "-0-") else v

        rows.append(
            {"entry_id": row[0].strip(), "name": clean(row[1]) or "", "entity_type": clean(row[2]),
             "programs": clean(row[3])}
        )  # fmt: skip
    return [r for r in rows if r["name"]]


async def load(session: AsyncSession, data: bytes, source_url: str) -> SanctionsLoad:
    """Replace the list with this download (caller commits)."""
    rows = parse_sdn(data)
    if not rows:
        raise ValueError("The sanctions file has no entries: kept the previous list.")
    await session.execute(delete(SanctionsLoad))
    loaded = SanctionsLoad(
        list_name=LIST_NAME, source_url=source_url,
        sha256=hashlib.sha256(data).hexdigest(), entries=len(rows),
    )  # fmt: skip
    session.add(loaded)
    await session.flush()
    session.add_all(
        SanctionsEntry(
            load_id=loaded.id, entry_id=str(r["entry_id"]), name=str(r["name"])[:500],
            normalized=normalize(str(r["name"]))[:500], entity_type=r["entity_type"],
            programs=(r["programs"] or "")[:500] or None,
        )
        for r in rows
    )  # fmt: skip
    return loaded


async def download() -> tuple[bytes, str]:
    url = get_settings().sanctions_list_url
    async with httpx.AsyncClient(timeout=120, transport=transport, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, url


@jobs.daily(JOB)
@jobs.handler(JOB)
async def refresh_job(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    if not get_settings().sanctions_list_url:
        return  # not configured: screening keeps refusing to answer without a list
    data, url = await download()
    await load(session, data, url)  # the queue commits


async def current(session: AsyncSession) -> SanctionsLoad | None:
    return await session.scalar(select(SanctionsLoad).order_by(SanctionsLoad.created_at.desc()))


@dataclass(frozen=True)
class Hit:
    screened_name: str
    listed_name: str
    entry_id: str
    programs: str | None
    score: float


async def screen(session: AsyncSession, names: list[str], threshold: float) -> list[Hit]:
    """Names that look like a listed one (same normalized words, or a close spelling)."""
    entries = list(await session.scalars(select(SanctionsEntry)))
    hits: list[Hit] = []
    for name in {n for n in names if n and n.strip()}:
        wanted = normalize(name)
        if not wanted:
            continue
        first = wanted.split(" ")[0]
        for entry in entries:
            if entry.normalized == wanted:
                score = 1.0
            elif first in entry.normalized:
                score = difflib.SequenceMatcher(None, wanted, entry.normalized).ratio()
            else:
                continue
            if score >= threshold:
                hits.append(Hit(name, entry.name, entry.entry_id, entry.programs, round(score, 3)))
    return hits
