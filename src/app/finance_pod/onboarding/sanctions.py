"""Sanctions screening against OFAC's Specially Designated Nationals (SDN) list.

The list is loaded into the database (from OFAC's published CSV, or an uploaded copy of it)
and names are compared after normalization (case, punctuation, legal suffixes such as
"Inc" or "LLC" dropped). A close match is a potential hit: it blocks activation until an
analyst clears it with a note. No list loaded is itself a failed check, never a pass.
"""

import csv
import io
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.finance_pod.onboarding.models import FpSanctionsEntry

SOURCE = "OFAC SDN"
MATCH_THRESHOLD = 0.92
_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l l c|ltd|limited|corp|corporation|co|company|plc|gmbh|sa|ag|"
    r"bv|nv|srl|spa|pvt|private|pte|lp|llp|the)\b"
)


class SanctionsListError(AppError):
    status_code = 502
    code = "sanctions_list_unavailable"


def normalize(name: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return " ".join(_SUFFIXES.sub(" ", text).split())


def _clean(value: str) -> str | None:
    return None if value.strip() in ("", "-0-") else value.strip()[:200]


def parse_sdn_csv(data: bytes) -> list[FpSanctionsEntry]:
    """OFAC sdn.csv: no header; ent_num, SDN_Name, SDN_Type, Program, ... ("-0-" = empty)."""
    loaded = utcnow()
    rows = []
    reader = csv.reader(io.StringIO(data.decode("latin-1")))
    for row in reader:
        if len(row) < 4 or not row[1].strip() or not row[0].strip().isdigit():
            continue
        name = row[1].strip()
        clean = _clean
        rows.append(
            FpSanctionsEntry(
                name=name[:400],
                normalized=normalize(name)[:400],
                entity_type=clean(row[2]),
                program=clean(row[3]),
                source=SOURCE,
                list_ref=row[0].strip(),
                loaded_at=loaded,
            )
        )
    if not rows:
        raise SanctionsListError("That file has no SDN entries (expected OFAC's sdn.csv).")
    return rows


async def load(session: AsyncSession, data: bytes | None = None) -> int:
    """Replace the list with OFAC's current one (downloaded), or the given sdn.csv."""
    if data is None:
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(get_settings().ofac_sdn_url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SanctionsListError(
                "OFAC's list couldn't be downloaded; upload sdn.csv instead."
            ) from exc
        data = resp.content
    rows = parse_sdn_csv(data)
    await session.execute(delete(FpSanctionsEntry).where(FpSanctionsEntry.source == SOURCE))
    session.add_all(rows)
    return len(rows)


@dataclass(frozen=True)
class ListInfo:
    entries: int
    loaded_at: str | None


async def info(session: AsyncSession) -> ListInfo:
    row = (
        await session.execute(
            select(func.count(), func.max(FpSanctionsEntry.loaded_at)).where(
                FpSanctionsEntry.source == SOURCE
            )
        )
    ).one()
    return ListInfo(entries=row[0], loaded_at=row[1].isoformat() if row[1] else None)


@dataclass(frozen=True)
class Hit:
    name: str
    program: str | None
    list_ref: str | None
    score: float


async def screen(session: AsyncSession, names: list[str]) -> list[Hit] | None:
    """Potential matches for any of the names; None when no list is loaded."""
    if (await info(session)).entries == 0:
        return None
    hits: dict[str, Hit] = {}
    for name in {n for n in names if n and n.strip()}:
        target = normalize(name)
        if not target:
            continue
        tokens = target.split()
        # Candidates share a word with the name (keeps it fast on ~20k entries)
        query = select(FpSanctionsEntry).where(
            FpSanctionsEntry.source == SOURCE,
            func.lower(FpSanctionsEntry.normalized).op("~")(
                r"\m(" + "|".join(re.escape(t) for t in tokens if len(t) > 2) + r")\M"
            ),
        )
        if not any(len(t) > 2 for t in tokens):
            query = select(FpSanctionsEntry).where(FpSanctionsEntry.normalized == target)
        for entry in await session.scalars(query.limit(500)):
            score = SequenceMatcher(None, target, entry.normalized).ratio()
            if score >= MATCH_THRESHOLD and (
                entry.name not in hits or hits[entry.name].score < score
            ):
                hits[entry.name] = Hit(entry.name, entry.program, entry.list_ref, round(score, 3))
    return sorted(hits.values(), key=lambda h: -h.score)
