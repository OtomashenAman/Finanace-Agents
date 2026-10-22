from typing import Annotated

from fastapi import APIRouter, Query

from src.app.auth.dependencies import CurrentUser
from src.app.core.db import SessionDep
from src.app.search import service
from src.app.search.schemas import SearchResults

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResults)
async def search(
    session: SessionDep, user: CurrentUser, q: Annotated[str, Query(max_length=100)] = ""
) -> SearchResults:
    """Runs, agents and (admins) people and legal entities matching q (2+ characters)."""
    return await service.search(session, user, q)
