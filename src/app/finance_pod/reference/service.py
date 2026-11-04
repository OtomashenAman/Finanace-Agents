"""Loading and reading the reference data.

An import is all or nothing: every row is checked, then every cross-reference (a lab's
cost centre, a budget's grant, a catalogue item's vendor) against the data as it will be
after the import. Any error and nothing is changed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext
from src.app.finance_pod.reference import workbook
from src.app.finance_pod.reference.models import (
    AuthorityScope,
    FpAuthorityTier,
    FpBudget,
    FpCatalogueItem,
    FpCostCentre,
    FpGrant,
    FpLab,
    FpProject,
    FpVendor,
    VendorStatus,
)
from src.app.finance_pod.reference.schemas import (
    AuthorityTierOut,
    BudgetOut,
    CatalogueItemOut,
    CostCentreOut,
    GrantOut,
    ImportResult,
    LabOut,
    ProjectOut,
    ReferenceOut,
    SheetResult,
    VendorOut,
)
from src.app.finance_pod.reference.workbook import (
    MAX_REPORTED_ERRORS,
    SHEET_TITLES,
    ReferenceInvalidError,
    Sheet,
)

# Sheets matched on one code column, and their model
_CODED: dict[Sheet, tuple[type[Any], str]] = {
    Sheet.COST_CENTRES: (FpCostCentre, "code"),
    Sheet.LABS: (FpLab, "code"),
    Sheet.PROJECTS: (FpProject, "code"),
    Sheet.GRANTS: (FpGrant, "code"),
    Sheet.CATALOGUE: (FpCatalogueItem, "item_code"),
    Sheet.VENDORS: (FpVendor, "code"),
}


def _budget_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("fiscal_year"),
        row.get("cost_centre_code"),
        row.get("grant_code"),
        row.get("category"),
    )


def _row_checks(parsed: workbook.ParsedWorkbook) -> None:
    """Checks within one row or one sheet (duplicates, enum values, either/or columns)."""
    errors = parsed.errors
    for sheet, rows in parsed.rows.items():
        title = SHEET_TITLES[sheet]
        seen: dict[Any, int] = {}
        for row in rows:
            n = row["_row"]
            if sheet in _CODED:
                key = row.get(_CODED[sheet][1])
            elif sheet is Sheet.BUDGETS:
                key = _budget_key(row)
            else:
                key = None
            if key is not None:
                if key in seen:
                    errors.append(f"Sheet '{title}' row {n}: same as row {seen[key]}.")
                seen[key] = n
            if sheet is Sheet.BUDGETS:
                if bool(row.get("cost_centre_code")) == bool(row.get("grant_code")):
                    errors.append(
                        f"Sheet '{title}' row {n}: give a cost centre or a grant (one of them)."
                    )
                for f in ("amount", "committed", "spent"):
                    if (row.get(f) or 0) < 0:
                        errors.append(f"Sheet '{title}' row {n}: {f} is negative.")
            if sheet is Sheet.GRANTS:
                start, end = row.get("start_date"), row.get("end_date")
                if start and end and end < start:
                    errors.append(f"Sheet '{title}' row {n}: end date is before start date.")
            if sheet is Sheet.CATALOGUE and (row.get("unit_price") or 0) < 0:
                errors.append(f"Sheet '{title}' row {n}: unit price is negative.")
            if sheet is Sheet.VENDORS and row.get("status"):
                status = str(row["status"]).lower()
                if status in {s.value for s in VendorStatus}:
                    row["status"] = VendorStatus(status)
                else:
                    errors.append(f"Sheet '{title}' row {n}: status must be approved or blocked.")
            if sheet is Sheet.AUTHORITY:
                scope = str(row.get("scope") or "").lower()
                if scope in {s.value for s in AuthorityScope}:
                    row["scope"] = AuthorityScope(scope)
                else:
                    errors.append(f"Sheet '{title}' row {n}: scope must be request or po.")
                if (row.get("min_amount") or 0) < 0:
                    errors.append(f"Sheet '{title}' row {n}: min amount is negative.")


async def _codes(session: AsyncSession, model: type[Any], column: str = "code") -> set[str]:
    return set(await session.scalars(select(getattr(model, column))))


@dataclass
class _Refs:
    """Codes that will exist after the import (stored, plus the file's)."""

    cost_centres: set[str]
    grants: set[str]
    vendors: set[str]


async def _refs(session: AsyncSession, parsed: workbook.ParsedWorkbook) -> _Refs:
    def from_file(sheet: Sheet) -> set[str]:
        return {r["code"] for r in parsed.rows.get(sheet, []) if r.get("code")}

    return _Refs(
        cost_centres=await _codes(session, FpCostCentre) | from_file(Sheet.COST_CENTRES),
        grants=await _codes(session, FpGrant) | from_file(Sheet.GRANTS),
        vendors=await _codes(session, FpVendor) | from_file(Sheet.VENDORS),
    )


def _cross_checks(parsed: workbook.ParsedWorkbook, refs: _Refs) -> None:
    links = {
        "cost_centre_code": ("cost centre", refs.cost_centres),
        "grant_code": ("grant", refs.grants),
        "vendor_code": ("vendor", refs.vendors),
    }
    for sheet, rows in parsed.rows.items():
        for row in rows:
            for column, (label, known) in links.items():
                value = row.get(column)
                if value and value not in known:
                    parsed.errors.append(
                        f"Sheet '{SHEET_TITLES[sheet]}' row {row['_row']}: {label} '{value}' "
                        f"isn't in the {label} list (add it to the workbook or load it first)."
                    )


async def _warnings(session: AsyncSession, parsed: workbook.ParsedWorkbook) -> list[str]:
    """People named in the data who can't act in the Finance POD (not a Finance Admin)."""
    admins = {
        e.lower()
        for e in await session.scalars(
            select(User.email).where(User.role == UserRole.FINANCE_ADMIN, User.is_active)
        )
    }
    named: dict[str, str] = {}
    for sheet in (Sheet.COST_CENTRES, Sheet.GRANTS, Sheet.AUTHORITY):
        for row in parsed.rows.get(sheet, []):
            for column in ("owner_email", "approver_email"):
                email = row.get(column)
                if email and email not in admins:
                    named.setdefault(email, SHEET_TITLES[sheet])
    return [
        f"{email} ({sheet}) has no active Finance Admin account, so approvals routed to them "
        "will wait until one is created."
        for email, sheet in named.items()
    ]


def _fields(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


async def _upsert_coded(
    session: AsyncSession, sheet: Sheet, rows: Sequence[dict[str, Any]]
) -> SheetResult:
    model, key = _CODED[sheet]
    existing = {getattr(o, key): o for o in await session.scalars(select(model))}
    created = updated = 0
    for row in rows:
        values = _fields(row)
        if values.get("active") is None:
            values.pop("active", None)
        if sheet is Sheet.VENDORS and not values.get("status"):
            values.pop("status", None)
        obj = existing.get(values[key])
        if obj is None:
            session.add(model(**values))
            created += 1
        else:
            changed = False
            for k, v in values.items():
                if getattr(obj, k) != v:
                    setattr(obj, k, v)
                    changed = True
            updated += changed
    return SheetResult(sheet=sheet, title=SHEET_TITLES[sheet], created=created, updated=updated)


async def _upsert_budgets(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> SheetResult:
    existing = {
        (b.fiscal_year, b.cost_centre_code, b.grant_code, b.category): b
        for b in await session.scalars(select(FpBudget))
    }
    created = updated = 0
    for row in rows:
        values = _fields(row)
        values["committed"] = values.get("committed") or 0
        values["spent"] = values.get("spent") or 0
        obj = existing.get(_budget_key(values))
        if obj is None:
            session.add(FpBudget(**values))
            created += 1
        else:
            changed = False
            for k in ("amount", "committed", "spent"):
                if getattr(obj, k) != values[k]:
                    setattr(obj, k, values[k])
                    changed = True
            updated += changed
    return SheetResult(
        sheet=Sheet.BUDGETS, title=SHEET_TITLES[Sheet.BUDGETS], created=created, updated=updated
    )


async def _replace_authority(session: AsyncSession, rows: Sequence[dict[str, Any]]) -> SheetResult:
    removed = len(list(await session.scalars(select(FpAuthorityTier.id))))
    await session.execute(delete(FpAuthorityTier))
    for row in rows:
        session.add(FpAuthorityTier(**_fields(row)))
    return SheetResult(
        sheet=Sheet.AUTHORITY,
        title=SHEET_TITLES[Sheet.AUTHORITY],
        created=len(rows),
        updated=0,
        removed=removed,
    )


async def import_workbook(
    session: AsyncSession, data: bytes, max_rows: int, actor: User, ctx: RequestContext
) -> ImportResult:
    parsed = workbook.parse(data, max_rows)
    _row_checks(parsed)
    _cross_checks(parsed, await _refs(session, parsed))
    if parsed.errors:
        shown = parsed.errors[:MAX_REPORTED_ERRORS]
        more = len(parsed.errors) - len(shown)
        raise ReferenceInvalidError(
            "Nothing was imported. " + " ".join(shown) + (f" (and {more} more)" if more else "")
        )
    warnings = await _warnings(session, parsed)
    results: list[SheetResult] = []
    for sheet in Sheet:  # cost centres and grants before what refers to them
        rows = parsed.rows.get(sheet)
        if rows is None:
            continue
        if sheet in _CODED:
            results.append(await _upsert_coded(session, sheet, rows))
        elif sheet is Sheet.BUDGETS:
            results.append(await _upsert_budgets(session, rows))
        else:
            results.append(await _replace_authority(session, rows))
    record_event(
        session,
        "fpod.reference_imported",
        ctx,
        actor_id=actor.id,
        summary="Loaded Finance POD reference data: "
        + ", ".join(f"{r.title} ({r.created} new, {r.updated} changed)" for r in results),
        sheets={r.sheet: r.model_dump(exclude={"sheet", "title"}) for r in results},
    )
    await session.commit()
    return ImportResult(sheets=results, warnings=warnings)


# --- reading ------------------------------------------------------------------------------


async def get_reference(session: AsyncSession) -> ReferenceOut:
    async def rows(model: type[Any], *order: Any) -> list[Any]:
        return list(await session.scalars(select(model).order_by(*order)))

    budgets = await rows(
        FpBudget,
        FpBudget.fiscal_year.desc(),
        FpBudget.cost_centre_code,
        FpBudget.grant_code,
        FpBudget.category,
    )
    return ReferenceOut(
        cost_centres=[
            CostCentreOut.model_validate(c, from_attributes=True)
            for c in await rows(FpCostCentre, FpCostCentre.code)
        ],
        labs=[
            LabOut.model_validate(c, from_attributes=True) for c in await rows(FpLab, FpLab.code)
        ],
        projects=[
            ProjectOut.model_validate(c, from_attributes=True)
            for c in await rows(FpProject, FpProject.code)
        ],
        grants=[
            GrantOut.model_validate(c, from_attributes=True)
            for c in await rows(FpGrant, FpGrant.code)
        ],
        budgets=[
            BudgetOut(
                fiscal_year=b.fiscal_year,
                cost_centre_code=b.cost_centre_code,
                grant_code=b.grant_code,
                category=b.category,
                amount=b.amount,
                committed=b.committed,
                spent=b.spent,
                remaining=b.amount - b.committed - b.spent,
            )
            for b in budgets
        ],
        catalogue=[
            CatalogueItemOut.model_validate(c, from_attributes=True)
            for c in await rows(FpCatalogueItem, FpCatalogueItem.item_code)
        ],
        vendors=[
            VendorOut.model_validate(c, from_attributes=True)
            for c in await rows(FpVendor, FpVendor.code)
        ],
        authority=[
            AuthorityTierOut.model_validate(c, from_attributes=True)
            for c in await rows(
                FpAuthorityTier,
                FpAuthorityTier.scope,
                FpAuthorityTier.cost_centre_code,
                FpAuthorityTier.min_amount,
            )
        ],
    )
