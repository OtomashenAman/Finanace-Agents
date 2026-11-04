"""The reference-data workbook: one sheet per kind of data, any subset of them.

Sheet names and headers are matched case- and punctuation-insensitively. A sheet that isn't
in the file leaves that data as it is. Lists (categories) are separated by commas or
semicolons. Every error names the sheet and the row.

    Cost centres      Code, Name, Owner Email, Active
    Labs              Code, Name, Cost Centre, Active
    Projects          Code, Name, Cost Centre, Grant, Active
    Grants            Code, Name, Sponsor, Cost Centre, Owner Email, Start Date, End Date,
                      Award Amount, Unallowable Categories, Active
    Budgets           Fiscal Year, Cost Centre, Grant, Category, Amount, Committed, Spent
    Catalogue         Item Code, Description, Category, Unit, Unit Price, Vendor,
                      Contract Ref, Contract End, Active
    Vendors           Code, Name, Email, Tax ID, Status, Categories
    Authority matrix  Scope, Cost Centre, Min Amount, Approver Email, Capacity
"""

import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from openpyxl import Workbook, load_workbook

from src.app.common.text_extraction.base import ExtractionError, check_zip_archive
from src.app.common.text_extraction.spreadsheet import CONTENT_TYPE, cell_text
from src.app.core.errors import AppError

MAX_REPORTED_ERRORS = 50
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ReferenceInvalidError(AppError):
    status_code = 422
    code = "reference_invalid"


class Sheet(StrEnum):
    COST_CENTRES = "cost_centres"
    LABS = "labs"
    PROJECTS = "projects"
    GRANTS = "grants"
    BUDGETS = "budgets"
    CATALOGUE = "catalogue"
    VENDORS = "vendors"
    AUTHORITY = "authority"


SHEET_TITLES: dict[Sheet, str] = {
    Sheet.COST_CENTRES: "Cost centres",
    Sheet.LABS: "Labs",
    Sheet.PROJECTS: "Projects",
    Sheet.GRANTS: "Grants",
    Sheet.BUDGETS: "Budgets",
    Sheet.CATALOGUE: "Catalogue",
    Sheet.VENDORS: "Vendors",
    Sheet.AUTHORITY: "Authority matrix",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


# --- cell converters (raise ValueError with a readable reason) ---------------------------


def _text(v: Any) -> str | None:
    s = cell_text(v)
    return s or None


def _email(v: Any) -> str | None:
    s = _text(v)
    if s is None:
        return None
    if not _EMAIL.match(s):
        raise ValueError(f"'{s}' is not an email address")
    return s.lower()


def _decimal(v: Any) -> Decimal | None:
    s = cell_text(v).replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"'{s}' is not a number") from exc
    if not d.is_finite():
        raise ValueError(f"'{s}' is not a number")
    return d.quantize(Decimal("0.01"))


def _date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = cell_text(v)
    try:
        return date.fromisoformat(s[:10])
    except ValueError as exc:
        raise ValueError(f"'{s}' is not a date (use YYYY-MM-DD)") from exc


def _int(v: Any) -> int | None:
    d = _decimal(v)
    if d is None:
        return None
    if d != d.to_integral_value():
        raise ValueError(f"'{cell_text(v)}' is not a whole number")
    return int(d)


_TRUE = {"yes", "y", "true", "1", "active", "approved"}
_FALSE = {"no", "n", "false", "0", "inactive", "retired"}


def _bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    s = cell_text(v).lower()
    if not s:
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f"'{s}' is not yes/no")


def _list(v: Any) -> list[str]:
    return [p.strip().lower() for p in re.split(r"[,;]", cell_text(v)) if p.strip()]


@dataclass(frozen=True)
class Column:
    name: str  # field name
    headers: tuple[str, ...]  # accepted header spellings, normalized
    convert: Callable[[Any], Any]
    required: bool = False


def _col(
    name: str, *headers: str, convert: Callable[[Any], Any] = _text, required: bool = False
) -> Column:
    return Column(name, tuple(_norm(h) for h in (name, *headers)), convert, required)


_ACTIVE = _col("active", "status", convert=_bool)

COLUMNS: dict[Sheet, tuple[Column, ...]] = {
    Sheet.COST_CENTRES: (
        _col("code", "cost centre", "cost center", "id", required=True),
        _col("name", required=True),
        _col("owner_email", "budget owner", "owner", convert=_email),
        _ACTIVE,
    ),
    Sheet.LABS: (
        _col("code", "lab", "id", required=True),
        _col("name", required=True),
        _col("cost_centre_code", "cost centre", "cost center"),
        _ACTIVE,
    ),
    Sheet.PROJECTS: (
        _col("code", "project", "id", required=True),
        _col("name", required=True),
        _col("cost_centre_code", "cost centre", "cost center"),
        _col("grant_code", "grant"),
        _ACTIVE,
    ),
    Sheet.GRANTS: (
        _col("code", "grant", "id", required=True),
        _col("name", required=True),
        _col("sponsor", "funder"),
        _col("cost_centre_code", "cost centre", "cost center"),
        _col("owner_email", "pi", "pi email", "principal investigator", convert=_email),
        _col("start_date", "start", convert=_date),
        _col("end_date", "end", convert=_date),
        _col("award_amount", "award", "amount", convert=_decimal),
        _col("unallowable_categories", "unallowable", "not allowed", convert=_list),
        _ACTIVE,
    ),
    Sheet.BUDGETS: (
        _col("fiscal_year", "year", "fy", convert=_int, required=True),
        _col("cost_centre_code", "cost centre", "cost center"),
        _col("grant_code", "grant"),
        _col("category", convert=lambda v: (_text(v) or "").lower() or None),
        _col("amount", "budget", convert=_decimal, required=True),
        _col("committed", "encumbered", convert=_decimal),
        _col("spent", "actual", "actuals", convert=_decimal),
    ),
    Sheet.CATALOGUE: (
        _col("item_code", "code", "item", "sku", required=True),
        _col("description", "name", required=True),
        _col("category", convert=lambda v: (_text(v) or "").lower() or None),
        _col("unit", "uom"),
        _col("unit_price", "price", "contract price", convert=_decimal, required=True),
        _col("vendor_code", "vendor"),
        _col("contract_ref", "contract"),
        _col("contract_end", "contract end date", convert=_date),
        _ACTIVE,
    ),
    Sheet.VENDORS: (
        _col("code", "vendor", "vendor code", "id", required=True),
        _col("name", "vendor name", required=True),
        _col("email", convert=_email),
        _col("tax_id", "tin", "ein", "vat"),
        _col("status"),
        _col("categories", convert=_list),
    ),
    Sheet.AUTHORITY: (
        _col("scope", required=True),
        _col("cost_centre_code", "cost centre", "cost center"),
        _col("min_amount", "from", "from amount", "amount", convert=_decimal, required=True),
        _col("approver_email", "approver", convert=_email, required=True),
        _col("capacity", "role", "title", required=True),
    ),
}

_SHEET_NAMES: dict[str, Sheet] = {
    _norm(alias): sheet
    for sheet, aliases in {
        Sheet.COST_CENTRES: ("cost centres", "cost centers", "costcentre", "costcenter"),
        Sheet.LABS: ("labs", "lab"),
        Sheet.PROJECTS: ("projects", "project"),
        Sheet.GRANTS: ("grants", "grant"),
        Sheet.BUDGETS: ("budgets", "budget"),
        Sheet.CATALOGUE: ("catalogue", "catalog", "contract prices", "prices"),
        Sheet.VENDORS: ("vendors", "approved vendors", "vendor list", "suppliers"),
        Sheet.AUTHORITY: ("authority matrix", "authority", "approval matrix"),
    }.items()
    for alias in aliases
}


@dataclass
class ParsedWorkbook:
    rows: dict[Sheet, list[dict[str, Any]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _parse_sheet(
    sheet: Sheet, title: str, values: list[tuple[Any, ...]], out: ParsedWorkbook, max_rows: int
) -> None:
    columns = COLUMNS[sheet]
    header_row = next((i for i, r in enumerate(values) if any(cell_text(c) for c in r)), None)
    if header_row is None:
        out.rows[sheet] = []
        return
    headers = [_norm(cell_text(c)) for c in values[header_row]]
    index: dict[str, int] = {}
    for col in columns:
        found = next((i for i, h in enumerate(headers) if h in col.headers), None)
        if found is not None:
            index[col.name] = found
        elif col.required:
            out.errors.append(f"Sheet '{title}': no '{col.name.replace('_', ' ')}' column.")
    if any(c.required and c.name not in index for c in columns):
        return
    rows: list[dict[str, Any]] = []
    data = values[header_row + 1 :]
    if len(data) > max_rows:
        out.errors.append(f"Sheet '{title}': more than {max_rows} rows.")
        return
    for n, raw in enumerate(data, start=header_row + 2):
        if not any(cell_text(c) for c in raw):
            continue
        row: dict[str, Any] = {}
        for col in columns:
            i = index.get(col.name)
            cell = raw[i] if i is not None and i < len(raw) else None
            try:
                value = col.convert(cell)
            except ValueError as exc:
                out.errors.append(f"Sheet '{title}' row {n}: {col.name.replace('_', ' ')} {exc}.")
                continue
            if col.required and value in (None, ""):
                out.errors.append(
                    f"Sheet '{title}' row {n}: {col.name.replace('_', ' ')} is empty."
                )
            if i is not None:
                row[col.name] = value
        row["_row"] = n
        rows.append(row)
    out.rows[sheet] = rows


def parse(data: bytes, max_rows: int) -> ParsedWorkbook:
    try:
        check_zip_archive(data, "XLSX")
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ExtractionError as exc:
        raise ReferenceInvalidError(str(exc)) from exc
    except Exception as exc:  # openpyxl raises many types for broken files
        raise ReferenceInvalidError("This XLSX file is damaged and can't be read.") from exc
    out = ParsedWorkbook()
    try:
        for ws in book.worksheets:
            sheet = _SHEET_NAMES.get(_norm(ws.title))
            if sheet is None:
                continue
            if sheet in out.rows:
                out.errors.append(f"Sheet '{ws.title}': {SHEET_TITLES[sheet]} appears twice.")
                continue
            _parse_sheet(sheet, ws.title, list(ws.iter_rows(values_only=True)), out, max_rows)
    finally:
        book.close()
    if not out.rows and not out.errors:
        names = ", ".join(SHEET_TITLES.values())
        raise ReferenceInvalidError(f"No reference sheets found. Expected any of: {names}.")
    return out


# --- template ----------------------------------------------------------------------------

_EXAMPLE: dict[Sheet, list[list[Any]]] = {
    Sheet.COST_CENTRES: [["CC-100", "Biology Department", "owner@example.org", "yes"]],
    Sheet.LABS: [["LAB-GEN", "Genomics Lab", "CC-100", "yes"]],
    Sheet.PROJECTS: [["PRJ-7", "Sequencing study", "CC-100", "GR-22", "yes"]],
    Sheet.GRANTS: [
        [
            "GR-22",
            "Sequencing grant",
            "National Science Foundation",
            "CC-100",
            "pi@example.org",
            "2026-01-01",
            "2027-12-31",
            250000,
            "alcohol; entertainment",
            "yes",
        ]
    ],
    Sheet.BUDGETS: [
        [2026, "CC-100", None, None, 120000, 10000, 45000],
        [2026, None, "GR-22", "lab supplies", 80000, 0, 12000],
    ],
    Sheet.CATALOGUE: [
        [
            "PIP-200",
            "Pipette tips 200ul, box of 960",
            "lab supplies",
            "box",
            42.50,
            "V-FISH",
            "CT-2026-01",
            "2026-12-31",
            "yes",
        ]
    ],
    Sheet.VENDORS: [
        [
            "V-FISH",
            "Lab Supply Co",
            "orders@labsupply.example",
            "12-3456789",
            "approved",
            "lab supplies",
        ]
    ],
    Sheet.AUTHORITY: [
        ["request", None, 0, "owner@example.org", "Budget owner"],
        ["request", None, 25000, "dean@example.org", "Dean"],
        ["po", None, 50000, "buyer@example.org", "Buyer"],
    ],
}


def template() -> tuple[bytes, str]:
    """A workbook with every sheet, its headers and one example row (to replace)."""
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    for sheet, title in SHEET_TITLES.items():
        ws = book.create_sheet(title)
        ws.append([_header(c) for c in COLUMNS[sheet]])
        for row in _EXAMPLE[sheet]:
            ws.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue(), CONTENT_TYPE


_HEADER_TEXT = {
    "cost_centre_code": "Cost Centre",
    "grant_code": "Grant",
    "vendor_code": "Vendor",
    "tax_id": "Tax ID",
    "owner_email": "Owner Email",
    "approver_email": "Approver Email",
}


def _header(col: Column) -> str:
    return _HEADER_TEXT.get(col.name) or col.name.replace("_", " ").title()
