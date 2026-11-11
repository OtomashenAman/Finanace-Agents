"""The fee schedule workbook: Fees, Contract prices, Tax rates.

An upload replaces all three in one go, or nothing at all when any row is wrong (each
problem is reported with its sheet and row). Agents read the schedule; only this upload
changes it.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import Workbook, load_workbook

from src.app.common.text_extraction.spreadsheet import CONTENT_TYPE, cell_text
from src.app.core.errors import AppError
from src.app.finance_pod.billing.models import FpContractPrice, FpFee, FpTaxRate

TURNAROUNDS = ("standard", "express", "rush")
MAX_ERRORS = 50


class FeeScheduleInvalidError(AppError):
    status_code = 422
    code = "fee_schedule_invalid"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", cell_text(value).lower())


def _decimal(v: Any, places: str = "0.01") -> Decimal | None:
    s = cell_text(v).replace(",", "").replace("$", "").replace("%", "").strip()
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"'{s}' is not a number") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"'{s}' is not a positive number")
    return d.quantize(Decimal(places))


def _date(v: Any) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(cell_text(v)[:10])
    except ValueError:
        raise ValueError(f"'{cell_text(v)}' is not a date (YYYY-MM-DD)") from None


def _text(v: Any) -> str | None:
    return cell_text(v).strip() or None


@dataclass
class Parsed:
    fees: list[FpFee] = field(default_factory=list)
    contracts: list[FpContractPrice] = field(default_factory=list)
    taxes: list[FpTaxRate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


SHEETS = {
    "fees": (
        "Fees",
        [
            "Service Code",
            "Service Name",
            "Stone Type",
            "Carat From",
            "Carat To",
            "Turnaround",
            "Fee",
            "Currency",
        ],
    ),
    "contracts": (
        "Contract prices",
        ["Client", "Service Code", "Price", "Discount %", "Contract Ref", "Valid To"],
    ),
    "taxes": ("Tax rates", ["Country", "Region", "Name", "Rate %"]),
}


def _rows(book: Any, title: str) -> tuple[dict[str, int], list[tuple[int, list[Any]]]] | None:
    sheet = next((ws for ws in book.worksheets if _norm(ws.title) == _norm(title)), None)
    if sheet is None:
        return None
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {}, []
    header = {_norm(h): i for i, h in enumerate(rows[0]) if _norm(h)}
    body = [
        (n, list(r)) for n, r in enumerate(rows[1:], start=2) if any(c not in (None, "") for c in r)
    ]
    return header, body


def parse(data: bytes) -> Parsed:
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise FeeScheduleInvalidError("That isn't an Excel workbook (.xlsx).") from None
    out = Parsed()

    def get(header: dict[str, int], row: list[Any], name: str) -> Any:
        i = header.get(_norm(name))
        return row[i] if i is not None and i < len(row) else None

    for key, (title, columns) in SHEETS.items():
        found = _rows(book, title)
        if found is None:
            out.errors.append(f"Sheet '{title}' is missing.")
            continue
        header, body = found
        missing = [c for c in columns[:3] if _norm(c) not in header]
        if missing and key != "taxes":
            out.errors.append(f"{title}: missing column(s) {', '.join(missing)}.")
            continue
        seen: set[tuple[Any, ...]] = set()
        for n, row in body:
            where = f"{title} row {n}"
            try:
                if key == "fees":
                    code = _text(get(header, row, "Service Code"))
                    name = _text(get(header, row, "Service Name"))
                    turnaround = (_text(get(header, row, "Turnaround")) or "standard").lower()
                    fee = _decimal(get(header, row, "Fee"))
                    if not code or not name or fee is None:
                        raise ValueError("service code, name and fee are required")
                    if turnaround not in TURNAROUNDS:
                        raise ValueError(f"turnaround must be one of {', '.join(TURNAROUNDS)}")
                    stone = (_text(get(header, row, "Stone Type")) or "").lower() or None
                    c_from = _decimal(get(header, row, "Carat From"), "0.001")
                    c_to = _decimal(get(header, row, "Carat To"), "0.001")
                    if c_from is not None and c_to is not None and c_to <= c_from:
                        raise ValueError("Carat To must be above Carat From")
                    ident = (code.upper(), stone, c_from, turnaround)
                    if ident in seen:
                        raise ValueError("the same fee appears twice")
                    seen.add(ident)
                    out.fees.append(
                        FpFee(
                            service_code=code.upper(),
                            service_name=name,
                            stone_type=stone,
                            carat_from=c_from,
                            carat_to=c_to,
                            turnaround=turnaround,
                            fee=fee,
                            currency=(_text(get(header, row, "Currency")) or "USD").upper()[:3],
                        )
                    )
                elif key == "contracts":
                    client = _text(get(header, row, "Client"))
                    code = _text(get(header, row, "Service Code"))
                    price = _decimal(get(header, row, "Price"))
                    disc = _decimal(get(header, row, "Discount %"))
                    if not client or not code:
                        raise ValueError("client and service code are required")
                    if (price is None) == (disc is None):
                        raise ValueError("give either a price or a discount %, not both")
                    if disc is not None and disc > 100:
                        raise ValueError("discount % must be 100 or less")
                    if (client, code.upper()) in seen:
                        raise ValueError("the same client and service appear twice")
                    seen.add((client, code.upper()))
                    out.contracts.append(
                        FpContractPrice(
                            client_code=client,
                            service_code=code.upper(),
                            price=price,
                            discount_pct=disc,
                            contract_ref=_text(get(header, row, "Contract Ref")),
                            valid_to=_date(get(header, row, "Valid To")),
                        )
                    )
                else:
                    country = (_text(get(header, row, "Country")) or "").upper()
                    rate = _decimal(get(header, row, "Rate %"), "0.001")
                    if len(country) != 2 or rate is None:
                        raise ValueError("a 2-letter country and a rate % are required")
                    region = (_text(get(header, row, "Region")) or "").upper() or None
                    if (country, region) in seen:
                        raise ValueError("the same country and region appear twice")
                    seen.add((country, region))
                    out.taxes.append(
                        FpTaxRate(
                            country=country,
                            region=region,
                            name=_text(get(header, row, "Name")) or f"Tax {country}",
                            rate_pct=rate,
                        )
                    )
            except ValueError as exc:
                if len(out.errors) < MAX_ERRORS:
                    out.errors.append(f"{where}: {exc}")
    if not out.fees and not out.errors:
        out.errors.append("Fees: no fee rows.")
    return out


def template() -> tuple[bytes, str]:
    """A workbook with the three sheets and example rows (a demo schedule)."""
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    examples: dict[str, list[list[Any]]] = {
        "fees": [
            ["GRD", "Diamond grading report", "diamond", 0, 1, "standard", 95, "USD"],
            ["GRD", "Diamond grading report", "diamond", 1, 3, "standard", 160, "USD"],
            ["GRD", "Diamond grading report", "diamond", 3, None, "standard", 290, "USD"],
            ["GRD", "Diamond grading report", "diamond", 0, 1, "express", 140, "USD"],
            ["GRD", "Diamond grading report", "diamond", 1, 3, "express", 230, "USD"],
            [
                "CID",
                "Coloured stone identification",
                "coloured",
                None,
                None,
                "standard",
                120,
                "USD",
            ],
            ["CID", "Coloured stone identification", "coloured", None, None, "express", 180, "USD"],
            ["ORG", "Origin report", "coloured", None, None, "standard", 250, "USD"],
            ["PRL", "Pearl identification", "pearl", None, None, "standard", 85, "USD"],
            ["LSR", "Laser inscription", None, None, None, "standard", 25, "USD"],
        ],
        "contracts": [["C-00002", "GRD", None, 15, "CT-LUMEN-2026", None]],
        "taxes": [
            ["US", "NY", "New York sales tax", 8.875],
            ["US", "PA", "Pennsylvania sales tax", 6],
            ["US", None, "No sales tax", 0],
        ],
    }
    for key, (title, columns) in SHEETS.items():
        ws = book.create_sheet(title)
        ws.append(columns)
        for row in examples[key]:
            ws.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue(), CONTENT_TYPE
