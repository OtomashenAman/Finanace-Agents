"""Header search: runs, agents and (for admins) people and legal entities, as the user may
see them in the rest of the app."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent
from src.app.agent_catalog.runs.service import search_runs
from src.app.agent_catalog.service import visible_agent_ids
from src.app.auth.models import User, UserRole
from src.app.entities.models import LegalEntity
from src.app.search.schemas import SearchHit, SearchResults

PER_KIND = 6


async def search(session: AsyncSession, user: User, query: str) -> SearchResults:
    term = query.strip()
    if len(term) < 2:
        return SearchResults(query=term, hits=[])
    pattern = f"%{term}%"
    hits: list[SearchHit] = []

    for run in await search_runs(session, user, term, PER_KIND):
        title = run.reference + (f" · {run.business_reference}" if run.business_reference else "")
        parts = [run.agent_name, run.status_label, run.preparer.full_name]
        if run.entity:
            parts.insert(1, run.entity.code)
        hits.append(
            SearchHit(
                kind="run",
                title=title,
                subtitle=" · ".join(parts),
                link=f"/catalog/{run.agent_key}/runs/{run.id}",
            )
        )

    agents = await session.scalars(
        select(Agent)
        .where(
            Agent.id.in_(visible_agent_ids(user)),
            or_(
                Agent.name.ilike(pattern),
                Agent.short_name.ilike(pattern),
                Agent.code.ilike(pattern),
            ),
        )
        .order_by(Agent.sort_order)
        .limit(PER_KIND)
    )
    hits += [
        SearchHit(kind="agent", title=a.name, subtitle=f"Agent {a.code}", link=f"/catalog/{a.key}")
        for a in agents
    ]

    if user.role == UserRole.FINANCE_ADMIN:
        people = await session.scalars(
            select(User)
            .where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
            .order_by(User.full_name)
            .limit(PER_KIND)
        )
        hits += [
            SearchHit(kind="user", title=u.full_name, subtitle=u.email, link="/admin/users")
            for u in people
        ]
        companies = await session.scalars(
            select(LegalEntity)
            .where(or_(LegalEntity.code.ilike(pattern), LegalEntity.name.ilike(pattern)))
            .order_by(LegalEntity.code)
            .limit(PER_KIND)
        )
        hits += [
            SearchHit(
                kind="entity",
                title=f"{e.code} · {e.name}",
                subtitle="Legal entity",
                link="/admin/entities",
            )
            for e in companies
        ]
    return SearchResults(query=term, hits=hits)
