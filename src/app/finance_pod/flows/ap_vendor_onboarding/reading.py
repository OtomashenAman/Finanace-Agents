"""Reading a vendor's tax form and bank letter, and checking a US tax ID.

Text-based documents are read with deterministic patterns (each value found is in the
document's own text). Scanned ones have no text: an AP analyst reads them by hand (there is
no OCR yet), and the step says so.
"""

import hashlib
import re
from dataclasses import dataclass

# IRS campus prefixes an EIN can start with (the first two digits)
EIN_PREFIXES = {
    *(f"{n:02d}" for n in range(1, 7)), *(f"{n:02d}" for n in range(10, 17)),
    *(f"{n:02d}" for n in range(20, 28)), *(f"{n:02d}" for n in range(30, 49)),
    *(f"{n:02d}" for n in range(50, 69)), *(f"{n:02d}" for n in range(71, 78)),
    *(f"{n:02d}" for n in range(80, 89)), *(f"{n:02d}" for n in range(90, 96)), "98", "99",
}  # fmt: skip


@dataclass(frozen=True)
class TaxDetails:
    form: str  # "W-9", "W-8BEN", "W-8BEN-E" or "unknown"
    legal_name: str | None
    tax_id: str | None
    tax_id_type: str  # EIN / SSN / ITIN / foreign / none


@dataclass(frozen=True)
class BankDetails:
    bank_name: str | None
    account_holder: str | None
    account_number: str
    routing_number: str | None
    iban: str | None

    def fingerprint(self) -> str:
        raw = "|".join(x or "" for x in (self.account_number, self.routing_number, self.iban))
        return hashlib.sha256(raw.encode()).hexdigest()


def _after(label: str, text: str) -> str | None:
    match = re.search(rf"(?im)^\s*{label}\s*[:\-]?\s*(.+)$", text)
    return match.group(1).strip()[:140] if match else None


def read_tax_form(text: str) -> TaxDetails | None:
    upper = text.upper()
    form = (
        "W-8BEN-E" if "W-8BEN-E" in upper else "W-8BEN" if "W-8BEN" in upper
        else "W-9" if re.search(r"W-?9\b", upper) else "unknown"
    )  # fmt: skip
    name = _after(r"(?:1\s*)?Name(?: \(as shown on your income tax return\))?", text) or _after(
        r"Name of (?:individual|organization)(?: that is the beneficial owner)?", text
    )
    ein = re.search(r"\b(\d{2}-\d{7})\b", text)
    ssn = re.search(r"\b(\d{3}-\d{2}-\d{4})\b", text)
    if ein:
        tin, kind = ein.group(1), "EIN"
    elif ssn:
        tin = ssn.group(1)
        kind = "ITIN" if tin.startswith("9") else "SSN"
    else:
        tin, kind = None, "foreign" if form.startswith("W-8") else "none"
    if form == "unknown" and tin is None:
        return None
    return TaxDetails(form=form, legal_name=name, tax_id=tin, tax_id_type=kind)


def aba_valid(routing: str) -> bool:
    if not re.fullmatch(r"\d{9}", routing):
        return False
    d = [int(x) for x in routing]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + d[2] + d[5] + d[8]) % 10 == 0


def read_bank_letter(text: str) -> BankDetails | None:
    account = re.search(
        r"(?i)account\s*(?:no\.?|number|#)\s*[:\-]?\s*([0-9][0-9 \-]{3,20}[0-9])", text
    )
    routing = re.search(
        r"(?i)(?:routing|aba|transit)\s*(?:no\.?|number|#)?\s*[:\-]?\s*(\d{9})\b", text
    )
    iban = re.search(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)\b", text)
    if not account and not iban:
        return None
    number = re.sub(r"[ \-]", "", account.group(1)) if account else ""
    if iban and not number:
        number = re.sub(r"\s", "", iban.group(1))[-10:]
    return BankDetails(
        bank_name=_after(r"Bank(?: name)?", text)
        or next(
            (ln.strip()[:140] for ln in text.splitlines() if re.search(r"(?i)\bbank\b", ln)), None
        ),
        account_holder=_after(r"(?:Account (?:holder|name)|Beneficiary)", text),
        account_number=number,
        routing_number=routing.group(1) if routing else None,
        iban=re.sub(r"\s", "", iban.group(1)) if iban else None,
    )


def mask(value: str | None, keep: int = 4) -> str | None:
    if not value:
        return None
    digits = value[-keep:]
    return "*" * max(len(value) - keep, 4) + digits


def check_tax_id(tax: TaxDetails) -> list[str]:
    """Problems with the tax ID's form (empty: it's well formed). This is not IRS TIN
    matching, which needs GIA's IRS registration."""
    problems: list[str] = []
    if tax.form == "W-9" and tax.tax_id is None:
        problems.append("the W-9 has no tax ID")
    if tax.tax_id_type == "EIN" and tax.tax_id and tax.tax_id[:2] not in EIN_PREFIXES:
        problems.append(f"EIN prefix {tax.tax_id[:2]} isn't one the IRS issues")
    if tax.tax_id_type in ("SSN", "ITIN") and tax.tax_id:
        area, group, serial = tax.tax_id.split("-")
        if tax.tax_id_type == "SSN" and (
            area in ("000", "666") or group == "00" or serial == "0000"
        ):
            problems.append("the SSN isn't a valid number")
    return problems
