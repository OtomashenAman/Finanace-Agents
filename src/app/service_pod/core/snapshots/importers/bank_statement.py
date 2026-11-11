"""A bank statement in whatever form the bank gives it, read into bank receipts.

Recognised by content, not by the file's name:
- OFX / QFX (bank and Quicken downloads), CAMT.053/054 (ISO 20022 XML), MT940 (SWIFT)
- CSV, TSV or text tables and Excel (.xlsx) in any bank's layout: the header row is found
  (even under a preamble), columns are matched by their usual names, one signed amount
  column or separate credit and debit columns, any common date and number format
- anything else (PDF, Word, a photo or scan): the AI reads the transactions. Every amount it
  reads from a document's text must be in that text; what it reads from an image is marked
  for a person to check

Only money in becomes a receipt (Bank-to-Invoice applies customer payments); money out is
counted. A line without a bank reference gets a stable one from its date, amount and
description, so the same statement imported twice gives the same receipts.
"""

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET  # DOCTYPE/ENTITY are refused before parsing (_safe_xml)
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import filetype
from openpyxl import load_workbook
from pydantic import BaseModel, Field, ValidationError

from src.app.common import documents
from src.app.common.text_extraction.delimited import decode_text
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.service_pod.common import ai
from src.app.service_pod.core.snapshots.contract import BankReceipt
from src.app.service_pod.core.snapshots.exceptions import SnapshotInvalidError

PROMPT_VERSION = "bank_statement/v1"
MAX_LINES = 5000


@dataclass
class Line:
    """One statement line, money in (positive) or out (negative)."""

    on: date
    amount: Decimal
    description: str
    payer: str | None = None
    reference: str | None = None
    currency: str | None = None
    cleared: bool = True


@dataclass
class Statement:
    receipts: list[BankReceipt]
    method: str  # how it was read, for the import's notes
    money_out: int = 0
    notes: list[str] = field(default_factory=list)


# --- values ----------------------------------------------------------------------------------

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def parse_amount(value: Any) -> Decimal | None:
    """'1,234.56', '(1,234.56)', '-1234.56', '1.234,56', '$ 99', '12.00 CR', '5.00 DR'."""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))
    s = str(value or "").strip()
    if not s:
        return None
    sign = -1 if s.startswith("(") and s.endswith(")") else 1
    if re.search(r"\bDR\.?$", s.upper()):  # '5.00 DR' (a debit); '12.00 CR' stays positive
        sign = -1
    s = re.sub(r"[^\d,.\-]", "", s)
    if s.startswith("-"):
        sign, s = -1, s[1:]
    s = s.replace("-", "")
    if "," in s and "." in s:
        s = (
            s.replace(",", "")
            if s.rfind(".") > s.rfind(",")
            else s.replace(".", "").replace(",", ".")
        )
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    try:
        return sign * Decimal(s) if s else None
    except InvalidOperation:
        return None


def parse_date(value: Any, day_first: bool = False) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{8}", s[:8]) and (len(s) == 8 or not s[8].isdigit()):  # 20261105 (OFX)
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    if m := re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s):
        y, mo, d = map(int, m.groups())
    elif m := re.match(r"(\d{1,2})[-/. ]([A-Za-z]{3})[A-Za-z]*[-/. ,]+(\d{2,4})", s):  # 05-Nov-2026
        d, mo, y = int(m.group(1)), MONTHS.get(m.group(2).lower(), 0), int(m.group(3))
    elif m := re.match(r"([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{2,4})", s):  # Nov 5, 2026
        mo, d, y = MONTHS.get(m.group(1).lower(), 0), int(m.group(2)), int(m.group(3))
    elif m := re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s):
        a, b, y = map(int, m.groups())
        d, mo = (a, b) if day_first or a > 12 else (b, a)
    else:
        return None
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _day_first(values: list[Any]) -> bool:
    """dd/mm or mm/dd: decided by the whole column (a first part above 12 is a day)."""
    for v in values:
        if isinstance(v, str) and (m := re.match(r"\s*(\d{1,2})[-/.](\d{1,2})[-/.]\d{2,4}", v)):
            if int(m.group(1)) > 12:
                return True
            if int(m.group(2)) > 12:
                return False
    return False


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


PAYER_PREFIX = re.compile(
    r"^(ach|wire|sepa|fps|bacs|chaps|transfer|trf|deposit|credit|incoming|inward|payment|"
    r"remittance|giro|eft|direct credit|mobile|online|bank)( (credit|transfer|from|in|"
    r"received|payment|deposit|remittance))*[: -]*",
    re.IGNORECASE,
)


def payer_from(description: str) -> str:
    """'WIRE FROM ACME CORP INV 101' -> 'ACME CORP INV 101' (the counterparty first)."""
    name = PAYER_PREFIX.sub("", description).strip(" :-/")
    name = re.sub(r"^from\s+", "", name, flags=re.IGNORECASE)
    return (name or description)[:200]


# --- tables: CSV, TSV, text, Excel ------------------------------------------------------------

COLUMNS: dict[str, tuple[str, ...]] = {
    "date": (
        "date",
        "transactiondate",
        "postingdate",
        "posteddate",
        "postdate",
        "bookingdate",
        "valuedate",
        "txndate",
        "entrydate",
        "processeddate",
        "effectivedate",
    ),
    "amount": ("amount", "transactionamount", "amt", "value", "netamount", "amountusd"),
    "credit": (
        "credit",
        "credits",
        "creditamount",
        "deposit",
        "deposits",
        "moneyin",
        "paidin",
        "cr",
        "in",
        "receipts",
        "inflow",
    ),
    "debit": (
        "debit",
        "debits",
        "debitamount",
        "withdrawal",
        "withdrawals",
        "moneyout",
        "paidout",
        "dr",
        "out",
        "payments",
        "outflow",
    ),
    "payer": (
        "payer",
        "payername",
        "from",
        "name",
        "payee",
        "counterparty",
        "counterpartyname",
        "remitter",
        "sender",
        "originator",
        "customer",
        "beneficiary",
    ),
    "description": (
        "description",
        "narrative",
        "details",
        "transactiondetails",
        "memo",
        "particulars",
        "transactiondescription",
        "remarks",
        "text",
        "information",
    ),
    "reference": (
        "reference",
        "ref",
        "transactionid",
        "transactionreference",
        "fitid",
        "checknumber",
        "chequenumber",
        "bankreference",
        "id",
        "referencenumber",
        "transactionref",
        "endtoendid",
        "utr",
    ),
    "currency": ("currency", "ccy", "curr", "currencycode"),
    "status": ("cleared", "status", "state"),
    "kind": ("type", "transactiontype", "drcr", "crdr", "creditdebit", "indicator", "dc"),
}


def _norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def _header_map(row: list[Any]) -> dict[str, int]:
    found: dict[str, int] = {}
    for i, cell in enumerate(row):
        key = _norm(cell)
        for col, names in COLUMNS.items():
            if col not in found and key in names:
                found[col] = i
                break
    return found


def from_table(rows: list[list[Any]]) -> list[Line]:
    """A table with a header row somewhere in its first rows."""
    header_at, cols = None, {}
    for i, row in enumerate(rows[:30]):
        cols = _header_map(row)
        if "date" in cols and ({"amount"} & cols.keys() or {"credit", "debit"} & cols.keys()):
            header_at = i
            break
    if header_at is None:
        raise SnapshotInvalidError(
            "No transaction table found: it needs a date column and an amount column (or "
            "credit and debit columns)."
        )
    body = [r for r in rows[header_at + 1 :] if any(_clean(c) for c in r)]

    def cell(row: list[Any], col: str) -> Any:
        i = cols.get(col)
        return row[i] if i is not None and i < len(row) else None

    day_first = _day_first([cell(r, "date") for r in body])
    lines = []
    for row in body:
        on = parse_date(cell(row, "date"), day_first)
        if on is None:
            continue  # a sub-total, a page footer, a balance line
        if "amount" in cols:
            amount = parse_amount(cell(row, "amount"))
            kind = _norm(cell(row, "kind"))
            if amount is not None and kind in ("debit", "dr", "d", "withdrawal", "dbit", "out"):
                amount = -abs(amount)
            elif amount is not None and kind in ("credit", "cr", "c", "deposit", "crdt", "in"):
                amount = abs(amount)
        else:
            credit, debit = parse_amount(cell(row, "credit")), parse_amount(cell(row, "debit"))
            amount = abs(credit) if credit else -abs(debit) if debit else None
        if not amount:
            continue
        description = _clean(cell(row, "description")) or _clean(cell(row, "payer"))
        status = _norm(cell(row, "status"))
        lines.append(
            Line(
                on=on,
                amount=amount,
                description=description,
                payer=_clean(cell(row, "payer")) or None,
                reference=_clean(cell(row, "reference")) or None,
                currency=_clean(cell(row, "currency")).upper()[:3] or None,
                cleared=status
                not in (
                    "pending",
                    "uncleared",
                    "no",
                    "false",
                    "n",
                    "0",
                    "pdng",
                    "authorised",
                    "authorized",
                    "hold",
                ),
            )
        )
    return lines


def _delimited(text: str) -> list[list[Any]]:
    sample = "\n".join(text.splitlines()[:40])
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(r) for r in csv.reader(io.StringIO(text), dialect)]


def _xlsx(data: bytes) -> list[list[Any]]:
    book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    for ws in book.worksheets:  # the first sheet with a transaction table
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if any("date" in _header_map(r) for r in rows[:30]):
            return rows
    return [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]


# --- OFX / QFX, CAMT, MT940 ------------------------------------------------------------------


def from_ofx(text: str) -> tuple[list[Line], str | None]:
    currency = m.group(1) if (m := re.search(r"<CURDEF>\s*([A-Z]{3})", text)) else None
    lines = []
    for block in re.findall(
        r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", text, re.S
    ):

        def tag(name: str, b: str = block) -> str | None:
            found = re.search(rf"<{name}>\s*([^<\r\n]*)", b)
            return found.group(1).strip() if found else None

        # DTPOSTED is YYYYMMDD, often with a time and zone after it
        amount, on = parse_amount(tag("TRNAMT")), parse_date((tag("DTPOSTED") or "")[:8])
        if amount is None or on is None:
            continue
        name, memo = tag("NAME") or tag("PAYEE") or "", tag("MEMO") or ""
        lines.append(
            Line(
                on=on,
                amount=amount,
                description=_clean(f"{name} {memo}"),
                payer=name or None,
                reference=tag("FITID") or tag("CHECKNUM") or tag("REFNUM"),
            )
        )
    return lines, currency


def _safe_xml(data: bytes) -> ET.Element:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise SnapshotInvalidError("XML with a DOCTYPE or entities isn't accepted.")
    try:
        return ET.fromstring(data)  # noqa: S314 - DOCTYPE/ENTITY refused above (no expansion)
    except ET.ParseError as exc:
        raise SnapshotInvalidError(f"The XML can't be read ({exc}).") from exc


def from_camt(data: bytes) -> list[Line]:
    root = _safe_xml(data)

    def local(el: ET.Element) -> str:
        return el.tag.rsplit("}", 1)[-1]

    def find(el: ET.Element, *path: str) -> ET.Element | None:
        current: ET.Element | None = el
        for name in path:
            current = (
                next((c for c in current if local(c) == name), None)
                if current is not None
                else None
            )
        return current

    def text(el: ET.Element | None) -> str:
        return (el.text or "").strip() if el is not None else ""

    def first(el: ET.Element, *paths: tuple[str, ...]) -> str:
        return next((t for p in paths if (t := text(find(el, *p)))), "")

    lines = []
    for entry in (e for e in root.iter() if local(e) == "Ntry"):
        amt = find(entry, "Amt")
        amount = parse_amount(text(amt))
        if amount is None or amt is None:
            continue
        if text(find(entry, "CdtDbtInd")) == "DBIT":
            amount = -abs(amount)
        on = parse_date(
            first(entry, ("BookgDt", "Dt"), ("BookgDt", "DtTm"), ("ValDt", "Dt"), ("ValDt", "DtTm"))
        )
        if on is None:
            continue
        tx = find(entry, "NtryDtls", "TxDtls")
        party = ""
        info = ""
        ref = ""
        if tx is not None:
            party = first(
                tx,
                ("RltdPties", "Dbtr", "Nm"),
                ("RltdPties", "Dbtr", "Pty", "Nm"),
                ("RltdPties", "Cdtr", "Nm"),
                ("RltdPties", "Cdtr", "Pty", "Nm"),
            )
            info = first(tx, ("RmtInf", "Ustrd"))
            ref = first(tx, ("Refs", "EndToEndId"), ("Refs", "AcctSvcrRef"), ("Refs", "TxId"))
        if ref.upper() == "NOTPROVIDED":
            ref = ""
        status = first(entry, ("Sts", "Cd"), ("Sts",))
        lines.append(
            Line(
                on=on,
                amount=amount,
                description=_clean(f"{party} {info} {text(find(entry, 'AddtlNtryInf'))}"),
                payer=party or None,
                reference=ref or first(entry, ("AcctSvcrRef",), ("NtryRef",)) or None,
                currency=amt.get("Ccy"),
                cleared=status.upper() not in ("PDNG", "INFO"),
            )
        )
    return lines


def from_mt940(text: str) -> tuple[list[Line], str | None]:
    currency = m.group(1) if (m := re.search(r":60[FM]:[CD]\d{6}([A-Z]{3})", text)) else None
    lines = []
    parts = re.split(r"(?=:61:)", text)
    for part in parts[1:]:
        head, _, rest = part[4:].partition("\n")
        m = re.match(r"(\d{6})(\d{4})?(R?[CD])[A-Z]?([\d,]+)(.*)", head.strip())
        if not m:
            continue
        on = parse_date("20" + m.group(1))
        amount = parse_amount(m.group(4))
        if on is None or amount is None:
            continue
        if m.group(3) in ("D", "RC"):  # a debit, or a credit reversed
            amount = -abs(amount)
        refs = m.group(5)
        ref = refs.split("//")[1].strip() if "//" in refs else refs[4:].strip()
        narrative = ""
        if (n := re.search(r":86:(.*?)(?=\n:\d{2}[A-Z]?:|\Z)", rest + "\n", re.S)) is not None:
            narrative = _clean(n.group(1))
        lines.append(
            Line(on=on, amount=amount, description=narrative or refs.strip(), reference=ref or None)
        )
    return lines, currency


# --- anything else: the AI reads it ------------------------------------------------------------

SYSTEM = """\
You read a bank statement and list its transactions. Report only what the statement shows.
Write every amount and reference exactly as printed; dates as YYYY-MM-DD. Money coming into
the account is "in", money leaving is "out". Skip opening and closing balances and totals.
"""


class _Txn(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    description: str
    payer: str | None = Field(description="Who the money came from (money in), if shown")
    reference: str | None = Field(description="The bank's reference for the line, if shown")
    amount: str = Field(description="As printed, without a sign")
    direction: Literal["in", "out"]


class _StatementRead(BaseModel):
    currency: str | None = Field(description="ISO code of the account's currency, if shown")
    transactions: list[_Txn]


async def from_document(
    data: bytes, filename: str, llm: LLMProvider
) -> tuple[list[Line], str | None, bool]:
    """(lines, currency, verified): verified = checked against the document's text."""
    prepared = documents.prepare(data, filename)
    if not prepared.readable:
        raise SnapshotInvalidError(f"The statement can't be read ({prepared.problem}).")
    stated = documents.digits(prepared.text) if prepared.text else ""

    def problems(r: _StatementRead) -> list[str]:
        out = []
        if not r.transactions:
            out.append("no transactions were found")
        if prepared.text:
            for t in r.transactions:
                if documents.digits(t.amount) not in stated:
                    out.append(f"amount {t.amount} isn't in the statement's text")
        return out[:10]

    try:
        result = await ai.extract(
            llm,
            system=SYSTEM,
            user=f"The statement ({filename}):\n\n{prepared.text}"
            if prepared.text
            else f"The statement ({filename}) is in the images.",
            schema=_StatementRead,
            prompt_version=PROMPT_VERSION,
            validate=problems,
            images=prepared.images,
        )
    except LLMError as exc:
        raise SnapshotInvalidError(
            "This file needs the AI to read it, and the AI isn't available. Upload a CSV, "
            "Excel, OFX, CAMT.053 or MT940 export instead."
        ) from exc
    except ai.AiOutputRejectedError as exc:
        raise SnapshotInvalidError(
            f"The statement couldn't be read reliably: {exc.message}."
        ) from exc
    lines = []
    for t in result.output.transactions:
        on, amount = parse_date(t.date), parse_amount(t.amount)
        if on is None or amount is None:
            continue
        lines.append(
            Line(
                on=on,
                amount=abs(amount) if t.direction == "in" else -abs(amount),
                description=_clean(t.description),
                payer=t.payer,
                reference=t.reference,
            )
        )
    return lines, (result.output.currency or "").upper()[:3] or None, bool(prepared.text)


# --- the reader --------------------------------------------------------------------------------


def _reference(line: Line, seen: dict[str, int]) -> str:
    """A stable reference for a line without one (the same statement gives the same one)."""
    key = f"{line.on.isoformat()}|{line.amount}|{line.description.lower()}"
    seen[key] = seen.get(key, 0) + 1
    digest = hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest()[:10].upper()
    return f"BNK-{line.on.strftime('%y%m%d')}-{digest}"


def to_receipts(lines: list[Line], currency: str) -> tuple[list[BankReceipt], int]:
    receipts: list[BankReceipt] = []
    seen: dict[str, int] = {}
    refs: set[str] = set()
    money_out = 0
    for line in lines[:MAX_LINES]:
        if line.amount <= 0:
            money_out += 1
            continue
        ref = (line.reference or "").strip()[:80] or _reference(line, seen)
        if ref.lower() in refs:  # a bank reused a reference (e.g. a cheque number)
            ref = f"{ref}-{line.on.strftime('%y%m%d')}-{len(refs)}"[:80]
        refs.add(ref.lower())
        try:
            receipts.append(
                BankReceipt(
                    reference=ref,
                    payer=(line.payer or payer_from(line.description) or "Unknown payer")[:200],
                    date=line.on,
                    amount=line.amount.quantize(Decimal("0.01")),
                    currency=(line.currency or currency).upper(),
                    cleared=line.cleared,
                    proof_reference=line.description[:200] or None,
                )
            )
        except ValidationError as exc:
            raise SnapshotInvalidError(f"Line of {line.on}: {exc.errors()[0]['msg']}") from exc
    return receipts, money_out


async def read(data: bytes, filename: str, currency: str, llm: LLMProvider) -> Statement:
    """Any statement file -> bank receipts (money in), in the snapshot's currency unless the
    statement says otherwise per line."""
    if not data:
        raise SnapshotInvalidError("The file is empty.")
    kind = filetype.guess_extension(data)
    text = decode_text(data) if kind in (None, "xml") else None
    notes: list[str] = []
    stated_currency: str | None = None
    if text is not None and re.search(r"OFXHEADER|<OFX>", text[:2000], re.IGNORECASE):
        lines, stated_currency = from_ofx(text)
        method = "OFX/QFX"
    elif text is not None and re.search(r"camt\.05[234]", text[:3000]):
        lines, method = from_camt(data), "CAMT (ISO 20022)"
    elif text is not None and ":61:" in text and re.search(r":20:|:25:", text):
        lines, stated_currency = from_mt940(text)
        method = "MT940"
    elif kind == "xlsx":
        lines, method = from_table(_xlsx(data)), "Excel"
    elif text is not None and (table := _table_or_none(text)) is not None:
        lines, method = table, "CSV"
    else:
        lines, stated_currency, verified = await from_document(data, filename, llm)
        method = "AI reading of the document"
        if not verified:
            notes.append(
                "Read from an image (a photo or scan): check each receipt's amount and reference "
                "against the statement before applying it."
            )
    if not lines:
        raise SnapshotInvalidError(f"No transactions found in the statement ({method}).")
    receipts, money_out = to_receipts(lines, stated_currency or currency)
    if not receipts:
        raise SnapshotInvalidError(
            f"The statement ({method}) has {money_out} payment(s) out and no money in: "
            "nothing to apply to invoices."
        )
    notes.insert(
        0,
        f"Read as {method}: {len(receipts)} receipt(s) (money in)"
        + (f"; {money_out} payment(s) out skipped" if money_out else "")
        + ".",
    )
    return Statement(receipts=receipts, method=method, money_out=money_out, notes=notes)


def _table_or_none(text: str) -> list[Line] | None:
    """The lines of a delimited table (CSV, TSV, ...), or None when the text has no
    transaction table (a text statement the AI reads instead)."""
    try:
        return from_table(_delimited(text))
    except SnapshotInvalidError:
        return None
