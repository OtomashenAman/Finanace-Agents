"""The request agent (Phase 1.1.2): enriches a purchase request before it's submitted.

a. suggests cost centre, lab, project and grant (AI, checked against the reference data;
   without AI, the requester's usual coding)
b. checks every line against the catalogue / contract prices (deterministic)
c. flags missing or inconsistent data; blocking problems stop the submit (deterministic)

It also turns free text into the request form (1.1.1.a in chat). It never saves or submits
anything itself: the requester accepts its suggestion or not.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.finance_pod.reference.models import (
    FpBudget,
    FpCatalogueItem,
    FpCostCentre,
    FpGrant,
    FpLab,
    FpProject,
    FpVendor,
)
from src.app.finance_pod.requests import prompt
from src.app.finance_pod.requests.models import FpPurchaseRequest, RequestStatus
from src.app.finance_pod.requests.schemas import (
    CodingSuggestion,
    DraftLine,
    Enrichment,
    PriceCheck,
    Problem,
    RequestDraft,
)
from src.app.finance_pod.settings.models import FinancePodSettings
from src.app.service_pod.common import ai

HISTORY_SIZE = 10
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"a", "an", "and", "the", "of", "for", "with", "to", "in", "box", "pack", "x"})


@dataclass
class Reference:
    """The reference data a request is checked against, keyed by code."""

    cost_centres: dict[str, FpCostCentre]
    labs: dict[str, FpLab]
    projects: dict[str, FpProject]
    grants: dict[str, FpGrant]
    catalogue: list[FpCatalogueItem]
    vendors: dict[str, FpVendor]
    categories: set[str]

    @classmethod
    async def load(cls, session: AsyncSession) -> "Reference":
        catalogue = list(await session.scalars(select(FpCatalogueItem)))
        grants = {g.code: g for g in await session.scalars(select(FpGrant))}
        vendors = {v.code: v for v in await session.scalars(select(FpVendor))}
        budget_categories = set(
            await session.scalars(select(FpBudget.category).where(FpBudget.category.is_not(None)))
        )
        categories = (
            {c.category for c in catalogue if c.category}
            | {c for g in grants.values() for c in g.unallowable_categories}
            | {c for v in vendors.values() for c in v.categories}
            | {c for c in budget_categories if c}
        )
        return cls(
            cost_centres={c.code: c for c in await session.scalars(select(FpCostCentre))},
            labs={c.code: c for c in await session.scalars(select(FpLab))},
            projects={c.code: c for c in await session.scalars(select(FpProject))},
            grants=grants,
            catalogue=catalogue,
            vendors=vendors,
            categories=categories,
        )


# --- b. price checks ---------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    jaccard = overlap / len(ta | tb)
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    # Needs real shared words, not just similar letters
    return max(jaccard, ratio) if overlap >= min(2, len(ta), len(tb)) else 0.0


MATCH_THRESHOLD = 0.6


def _in_force(item: FpCatalogueItem, today: date) -> bool:
    return item.active and (item.contract_end is None or item.contract_end >= today)


def price_checks(request: FpPurchaseRequest, ref: Reference, today: date) -> list[PriceCheck]:
    items = [i for i in ref.catalogue if _in_force(i, today)]
    by_code = {i.item_code: i for i in items}
    checks = []
    for n, line in enumerate(request.lines, start=1):
        item, how = None, None
        if line.catalogue_item_code and line.catalogue_item_code in by_code:
            item, how = by_code[line.catalogue_item_code], "item_code"
        else:
            scored = [(_similarity(line.description, i.description), i) for i in items]
            best = max(scored, key=lambda s: s[0], default=(0.0, None))
            if best[1] is not None and best[0] >= MATCH_THRESHOLD:
                item, how = best[1], "description"
        if item is None:
            checks.append(PriceCheck(line=n, status="no_match"))
            continue
        vendor = ref.vendors.get(item.vendor_code or "")
        common = {
            "line": n,
            "item_code": item.item_code,
            "item_description": item.description,
            "contract_price": item.unit_price,
            "vendor_code": item.vendor_code,
            "vendor_name": vendor.name if vendor else None,
            "contract_ref": item.contract_ref,
            "how": how,
        }
        if line.unit_price is None:
            checks.append(PriceCheck(status="no_estimate", **common))
            continue
        diff = ((line.unit_price - item.unit_price) * line.quantity).quantize(Decimal("0.01"))
        status = "matches" if diff == 0 else "above_contract" if diff > 0 else "below_contract"
        checks.append(PriceCheck(status=status, difference=diff, **common))
    return checks


# --- c. missing / inconsistent data --------------------------------------------------------


def problems(request: FpPurchaseRequest, ref: Reference, today: date) -> list[Problem]:
    out: list[Problem] = []

    def flag(field: str, message: str, *, blocking: bool = True) -> None:
        out.append(Problem(field=field, message=message, blocking=blocking))

    if not request.purpose.strip():
        flag("purpose", "Say what it's for: the budget and grant checks need it.")
    if not request.lines:
        flag("lines", "Add at least one item or service.")
    for n, line in enumerate(request.lines, start=1):
        if line.unit_price is None:
            flag(f"lines.{n}.unit_price", f"Line {n}: estimate the unit price.")
    if request.needed_by is None:
        flag("needed_by", "Give the date it's needed by.")
    elif request.needed_by < today:
        flag("needed_by", "The needed-by date is in the past.")

    cc = ref.cost_centres.get(request.cost_centre_code or "")
    if request.cost_centre_code is None:
        flag("cost_centre_code", "Choose the cost centre that pays for it.")
    elif cc is None:
        flag("cost_centre_code", f"Cost centre {request.cost_centre_code} doesn't exist.")
    elif not cc.active:
        flag("cost_centre_code", f"Cost centre {cc.code} is no longer active.")

    for field, table, label in (
        ("lab_code", ref.labs, "Lab"),
        ("project_code", ref.projects, "Project"),
    ):
        code = getattr(request, field)
        if code is None:
            continue
        row = table.get(code)
        if row is None:
            flag(field, f"{label} {code} doesn't exist.")
        elif not row.active:
            flag(field, f"{label} {code} is no longer active.")
        elif cc and row.cost_centre_code and row.cost_centre_code != cc.code:
            flag(
                field,
                f"{label} {code} belongs to cost centre {row.cost_centre_code}, not {cc.code}.",
                blocking=False,
            )

    project = ref.projects.get(request.project_code or "")
    if project and project.grant_code and request.grant_code != project.grant_code:
        flag(
            "grant_code",
            f"Project {project.code} is funded by grant {project.grant_code}.",
            blocking=False,
        )

    if request.grant_code is not None:
        grant = ref.grants.get(request.grant_code)
        if grant is None:
            flag("grant_code", f"Grant {request.grant_code} doesn't exist.")
        elif not grant.active:
            flag("grant_code", f"Grant {grant.code} is no longer active.")
        else:
            when = request.needed_by or today
            if grant.end_date and when > grant.end_date:
                flag("grant_code", f"Grant {grant.code} ends on {grant.end_date.isoformat()}.")
            if grant.start_date and when < grant.start_date:
                flag(
                    "grant_code",
                    f"Grant {grant.code} starts on {grant.start_date.isoformat()}.",
                )
            for n, line in enumerate(request.lines, start=1):
                if line.category is None:
                    flag(
                        f"lines.{n}.category",
                        f"Line {n}: add a category so the grant's rules can be checked.",
                        blocking=False,
                    )
                elif line.category in grant.unallowable_categories:
                    flag(
                        f"lines.{n}.category",
                        f"Line {n}: grant {grant.code} doesn't allow '{line.category}'; "
                        "the budget check will stop it.",
                        blocking=False,
                    )
    return out


def quotes_needed(request: FpPurchaseRequest, settings: FinancePodSettings) -> int:
    return settings.min_quotes if request.total >= settings.purchasing_threshold else 0


# --- a. coding suggestion ------------------------------------------------------------------


def _without_quoted_words(text: str, source: str) -> str:
    """`text` without the words it quotes from `source` (e.g. "run 14" from the purpose)."""
    quoted = set(_WORD.findall(source.lower()))
    kept = []
    for word in text.split():
        tokens = _WORD.findall(word.lower())
        if tokens and all(t in quoted for t in tokens):
            continue
        kept.append(word)
    return " ".join(kept)


def _coding_problems(
    read: prompt.CodingRead, request: FpPurchaseRequest, ref: Reference, today: date
) -> list[str]:
    found = []
    for code, table, label in (
        (read.cost_centre_code, ref.cost_centres, "cost centre"),
        (read.lab_code, ref.labs, "lab"),
        (read.project_code, ref.projects, "project"),
        (read.grant_code, ref.grants, "grant"),
    ):
        if code is not None and (code not in table or not table[code].active):
            found.append(f"{label} {code} isn't an active code")
    if found:
        return found
    if read.cost_centre_code is None:
        found.append("no cost centre")
    for code, table, label in (
        (read.lab_code, ref.labs, "lab"),
        (read.project_code, ref.projects, "project"),
    ):
        row = table.get(code or "")
        if row and row.cost_centre_code and row.cost_centre_code != read.cost_centre_code:
            found.append(f"{label} {code} belongs to another cost centre")
    grant = ref.grants.get(read.grant_code or "")
    when = request.needed_by or today
    if grant and (
        (grant.end_date and when > grant.end_date) or (grant.start_date and when < grant.start_date)
    ):
        found.append(f"grant {grant.code} doesn't cover the needed-by date")
    if len(read.line_categories) != len(request.lines):
        found.append("one category per line expected")
    unknown = [c for c in read.line_categories if c and c.lower() not in ref.categories]
    if unknown:
        found.append(f"unknown categories {', '.join(unknown)}")
    # Codes (PRJ-7) and words quoted from the request ("run 14", "200ul") may be cited;
    # a figure of the model's own may not
    reason = read.reason
    for code in sorted(
        [*ref.cost_centres, *ref.labs, *ref.projects, *ref.grants], key=len, reverse=True
    ):
        reason = reason.replace(code, "")
    reason = _without_quoted_words(reason, _request_text(request))
    if ai.states_number(reason):
        found.append("the reason states figures not in the request")
    return found


def _lists(ref: Reference) -> str:
    def rows(title: str, items: list[str]) -> str:
        return f"{title}:\n" + ("\n".join(items) if items else "(none)")

    return "\n\n".join(
        [
            rows(
                "Cost centres",
                [f"- {c.code}: {c.name}" for c in ref.cost_centres.values() if c.active],
            ),
            rows(
                "Labs",
                [
                    f"- {c.code}: {c.name} (cost centre {c.cost_centre_code or '-'})"
                    for c in ref.labs.values()
                    if c.active
                ],
            ),
            rows(
                "Projects",
                [
                    f"- {c.code}: {c.name} (cost centre {c.cost_centre_code or '-'}, "
                    f"grant {c.grant_code or '-'})"
                    for c in ref.projects.values()
                    if c.active
                ],
            ),
            rows(
                "Grants",
                [
                    f"- {g.code}: {g.name} (sponsor {g.sponsor or '-'}, "
                    f"{g.start_date or '?'} to {g.end_date or '?'}, "
                    f"not allowed: {', '.join(g.unallowable_categories) or 'nothing listed'})"
                    for g in ref.grants.values()
                    if g.active
                ],
            ),
            rows("Categories", sorted(f"- {c}" for c in ref.categories)),
        ]
    )


def _request_text(request: FpPurchaseRequest) -> str:
    lines = "\n".join(
        f"{n}. {ln.description} (quantity {ln.quantity}{' ' + ln.unit if ln.unit else ''})"
        for n, ln in enumerate(request.lines, start=1)
    )
    return (
        f"Title: {request.title}\nPurpose: {request.purpose or '(none given)'}\n"
        f"Needed by: {request.needed_by or '(not given)'}\nLines:\n{lines or '(none)'}"
    )


async def _from_history(
    session: AsyncSession, request: FpPurchaseRequest, ref: Reference, today: date
) -> CodingSuggestion | None:
    """The coding the requester used most on their recent requests, if still valid."""
    rows = await session.execute(
        select(
            FpPurchaseRequest.cost_centre_code,
            FpPurchaseRequest.lab_code,
            FpPurchaseRequest.project_code,
            FpPurchaseRequest.grant_code,
        )
        .where(
            FpPurchaseRequest.requester_id == request.requester_id,
            FpPurchaseRequest.id != request.id,
            FpPurchaseRequest.cost_centre_code.is_not(None),
            FpPurchaseRequest.status.in_(
                [RequestStatus.SUBMITTED, RequestStatus.APPROVED, RequestStatus.QUERIED]
            ),
        )
        .order_by(FpPurchaseRequest.created_at.desc())
        .limit(HISTORY_SIZE)
    )
    for coding, _ in Counter(tuple(r) for r in rows).most_common():
        read = prompt.CodingRead(
            cost_centre_code=coding[0],
            lab_code=coding[1],
            project_code=coding[2],
            grant_code=coding[3],
            line_categories=[ln.category for ln in request.lines],
            reason="The coding you used most on your recent requests.",
        )
        if not _coding_problems(read, request, ref, today):
            return CodingSuggestion(**read.model_dump(), source="history")
    return None


async def suggest_coding(
    session: AsyncSession,
    llm: LLMProvider,
    request: FpPurchaseRequest,
    ref: Reference,
    today: date,
) -> tuple[CodingSuggestion | None, str | None]:
    """(suggestion, note): the AI's checked suggestion, else the requester's usual coding,
    else none, with a note saying why."""
    try:
        result = await ai.extract(
            llm,
            system=prompt.CODING_SYSTEM,
            user=f"{_lists(ref)}\n\nThe request:\n{_request_text(request)}",
            schema=prompt.CodingRead,
            prompt_version=prompt.CODING_PROMPT_VERSION,
            validate=lambda r: _coding_problems(r, request, ref, today),
        )
    except (LLMError, ai.AiOutputRejectedError) as exc:
        note = (
            "The AI isn't available"
            if isinstance(exc, LLMError)
            else f"The AI's suggestion didn't hold up ({exc.message.split(': ', 1)[-1]})"
        )
        fallback = await _from_history(session, request, ref, today)
        if fallback is None:
            return None, f"{note}, and you have no earlier requests to go by."
        return fallback, f"{note}; showing the coding you usually use."
    read = result.output
    return (
        CodingSuggestion(
            **read.model_dump(),
            source="ai",
            provenance=result.provenance.as_dict(),
        ),
        None,
    )


async def enrich(
    session: AsyncSession,
    request: FpPurchaseRequest,
    settings: FinancePodSettings,
    *,
    llm: LLMProvider | None,
) -> Enrichment:
    """Run the checks (b, c); with `llm`, a fresh coding suggestion (a), else keep the last."""
    today = utcnow().date()
    ref = await Reference.load(session)
    previous = Enrichment.model_validate(request.enrichment) if request.enrichment else None
    if llm is not None:
        suggestion, note = await suggest_coding(session, llm, request, ref, today)
    else:
        suggestion = previous.suggestion if previous else None
        note = previous.suggestion_note if previous else None
    found = problems(request, ref, today)
    needed = quotes_needed(request, settings)
    if needed:
        found.append(
            Problem(
                field="quotes",
                message=(
                    f"At or above the purchasing threshold ({settings.purchasing_threshold} "
                    f"{settings.currency}): sourcing will collect {needed} quotes. Attach any "
                    "you already have."
                ),
                blocking=False,
            )
        )
    return Enrichment(
        ran_at=utcnow(),
        suggestion=suggestion,
        suggestion_note=note,
        price_checks=price_checks(request, ref, today),
        problems=found,
        quotes_needed=needed,
    )


# --- free text -> form -----------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> set[Decimal]:
    found = set()
    for raw in _NUMBER.findall(text):
        try:
            found.add(Decimal(raw.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return found


def _number(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(value.replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() and d >= 0 else None


async def draft_from_text(llm: LLMProvider, text: str) -> RequestDraft:
    """The request form filled from free text. Prices must be in the text; a quantity that
    isn't becomes 1 with a note; a date in the past is dropped. Nothing is saved."""
    today = utcnow().date()
    result = await ai.extract(
        llm,
        system=prompt.DRAFT_SYSTEM.format(today=today.isoformat()),
        user=text,
        schema=prompt.DraftRead,
        prompt_version=prompt.DRAFT_PROMPT_VERSION,
        validate=lambda r: [] if r.lines else ["no items found in the text"],
    )
    read = result.output
    stated = _numbers_in(text)
    notes = list(read.notes)
    lines = []
    for n, ln in enumerate(read.lines, start=1):
        quantity = _number(ln.quantity)
        if quantity is None or quantity == 0 or quantity.normalize() not in stated:
            if quantity not in (None, Decimal(1)):
                notes.append(f"Line {n}: the quantity isn't in your text; check it.")
            quantity = Decimal(1)
        price = _number(ln.unit_price)
        if price is not None and price.normalize() not in stated:
            notes.append(f"Line {n}: the AI's price isn't in your text, so it was left out.")
            price = None
        lines.append(
            DraftLine(
                description=ln.description[:500],
                quantity=quantity,
                unit=(ln.unit or None) and ln.unit[:20],
                unit_price=price.quantize(Decimal("0.01")) if price is not None else None,
            )
        )
    needed_by = None
    if read.needed_by:
        try:
            needed_by = date.fromisoformat(read.needed_by)
        except ValueError:
            notes.append("The needed-by date couldn't be read; enter it.")
        else:
            if needed_by < today:
                notes.append("The needed-by date was in the past, so it was left out.")
                needed_by = None
    return RequestDraft(
        title=read.title[:200] or "Purchase request",
        purpose=read.purpose[:4000],
        needed_by=needed_by,
        lines=lines,
        notes=notes,
        provenance=result.provenance.as_dict(),
    )
