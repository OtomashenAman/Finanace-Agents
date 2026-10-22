from typing import Literal

from pydantic import BaseModel

HitKind = Literal["run", "agent", "user", "entity"]


class SearchHit(BaseModel):
    kind: HitKind
    title: str  # e.g. "RUN-01006 · Bill 195"
    subtitle: str | None  # e.g. "AP Invoice · Pending approval · Demo User"
    link: str  # app path to open


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]
