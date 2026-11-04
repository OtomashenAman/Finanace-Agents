"""The onboarding agent (Phase 1.5.1.b-c): reads the vendor's tax form and bank letter and
checks them against what the vendor entered on the portal.

Reading is AI (vision for scans and photos); what it reads from a document's text must be
in that text, and what it reads from an image is marked unverified. The checks are
computed: tax ID format, tax ID and legal name against the form, routing-number checksum,
account and routing numbers against the bank letter, the account holder's name, and the
sanctions screen. A failed check blocks verification; some can be cleared with a note.
"""

import re
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from src.app.core.llm.base import LLMError, LLMProvider
from src.app.data_sources import crypto
from src.app.finance_pod import documents
from src.app.finance_pod.onboarding import sanctions
from src.app.finance_pod.onboarding.models import DocumentKind, FpOnboarding, FpOnboardingDocument
from src.app.service_pod.common import ai

PROMPT_VERSION = "fpod_onboarding/v1"
EIN = re.compile(r"^\d{2}-?\d{7}$")
SSN = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
NAME_MATCH = 0.85

SYSTEM = """\
You read a vendor's onboarding document: a US tax form (W-9, W-8BEN, W-8BEN-E) or a bank
letter confirming account details. Report only what the document states; null otherwise.
Write numbers exactly as printed. Never guess a digit you can't read.
"""


class DocRead(BaseModel):
    document_type: Literal["W-9", "W-8BEN", "W-8BEN-E", "bank_letter", "other"]
    legal_name: str | None = Field(description="Name of the taxpayer / account holder")
    tax_id: str | None = Field(description="EIN, SSN or foreign TIN as printed")
    address: str | None
    bank_name: str | None
    account_name: str | None = Field(description="Account holder name on a bank letter")
    routing_number: str | None = Field(description="ABA routing / sort code as printed")
    account_number: str | None
    on_bank_letterhead: bool | None
    signed: bool | None


Check = dict[str, Any]  # {key, label, status: pass|fail|warn|unknown, detail, clearable}


def _check(key: str, label: str, status: str, detail: str, clearable: bool = False) -> Check:
    return {"key": key, "label": label, "status": status, "detail": detail, "clearable": clearable}


def _similar(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, sanctions.normalize(a), sanctions.normalize(b)).ratio()


def aba_valid(routing: str) -> bool:
    """US ABA routing number checksum (3-7-1 weights)."""
    if not re.fullmatch(r"\d{9}", routing):
        return False
    d = [int(c) for c in routing]
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0


async def _read(
    llm: LLMProvider, doc: FpOnboardingDocument
) -> tuple[dict[str, Any] | None, str | None]:
    prepared = documents.prepare(doc.content, doc.filename)
    if not prepared.readable:
        return None, f"{doc.filename} can't be read ({prepared.problem})"
    stated = documents.digits(prepared.text) if prepared.text else ""

    def problems(r: DocRead) -> list[str]:
        if not prepared.text:
            return []
        return [
            f"{label} {value} isn't in the document's text"
            for label, value in (
                ("tax ID", r.tax_id),
                ("routing number", r.routing_number),
                ("account number", r.account_number),
            )
            if value and documents.digits(value) and documents.digits(value) not in stated
        ]

    try:
        result = await ai.extract(
            llm,
            system=SYSTEM,
            user=(
                f"The document ({doc.filename}):\n\n{prepared.text}"
                if prepared.text
                else f"The document ({doc.filename}) is in the images."
            ),
            schema=DocRead,
            prompt_version=PROMPT_VERSION,
            validate=problems,
            images=prepared.images,
        )
    except LLMError:
        return None, "the AI isn't available"
    except ai.AiOutputRejectedError as exc:
        return None, f"the AI's reading of {doc.filename} didn't hold up ({exc.message})"
    return {
        **result.output.model_dump(),
        "verified": bool(prepared.text),
        "filename": doc.filename,
        "provenance": result.provenance.as_dict(),
    }, None


async def run(session: AsyncSession, llm: LLMProvider, onboarding: FpOnboarding) -> None:
    """Read the documents and run the checks; stores both on the onboarding."""
    docs = list(
        await session.scalars(
            select(FpOnboardingDocument)
            .options(undefer(FpOnboardingDocument.content))
            .where(FpOnboardingDocument.onboarding_id == onboarding.id)
        )
    )
    tax_doc = next((d for d in docs if d.kind == DocumentKind.TAX_FORM), None)
    bank_doc = next((d for d in docs if d.kind == DocumentKind.BANK_LETTER), None)
    extraction: dict[str, Any] = {"notes": []}
    for key, doc in (("tax_form", tax_doc), ("bank_letter", bank_doc)):
        if doc is None:
            continue
        read, problem = await _read(llm, doc)
        extraction[key] = read
        if problem:
            extraction["notes"].append(problem)

    routing = crypto.decrypt(onboarding.routing_number_enc) if onboarding.routing_number_enc else ""
    account = crypto.decrypt(onboarding.account_number_enc) if onboarding.account_number_enc else ""
    checks: list[Check] = []

    missing = [
        label for label, doc in (("tax form", tax_doc), ("bank letter", bank_doc)) if not doc
    ]
    checks.append(
        _check(
            "documents",
            "Tax form and bank letter received",
            "fail" if missing else "pass",
            f"Missing: {', '.join(missing)}." if missing else "Both received.",
        )
    )

    tax_id = (onboarding.tax_id or "").strip()
    if onboarding.tax_form == "W-9":
        ok = bool(EIN.match(tax_id) or SSN.match(tax_id))
        checks.append(
            _check(
                "tax_id_format",
                "Tax ID format (EIN or SSN)",
                "pass" if ok else "fail",
                "Valid format." if ok else f"'{tax_id}' isn't a 9-digit EIN or SSN.",
            )
        )
    else:
        checks.append(
            _check(
                "tax_id_format",
                "Foreign tax ID",
                "warn" if tax_id else "fail",
                "Foreign TIN: check it against the W-8." if tax_id else "No tax ID given.",
                clearable=bool(tax_id),
            )
        )

    form = extraction.get("tax_form")
    if form and not documents.digits(form.get("tax_id")):
        # Read, but no tax ID found on it: nothing to compare, a person looks
        checks.append(
            _check(
                "tax_id_matches_form",
                "Tax ID matches the tax form",
                "unknown",
                "No tax ID could be read on the tax form: compare it by eye.",
                clearable=True,
            )
        )
    elif form:
        same_id = documents.digits(form.get("tax_id")) == documents.digits(tax_id) and bool(tax_id)
        unverified = "" if form.get("verified") else " (read from an image: confirm by eye)"
        checks.append(
            _check(
                "tax_id_matches_form",
                "Tax ID matches the tax form",
                ("pass" if form.get("verified") else "warn") if same_id else "fail",
                (
                    f"Same as the form{unverified}."
                    if same_id
                    else f"Portal says {tax_id or '-'}, the form says {form.get('tax_id') or '-'}."
                ),
                clearable=same_id,
            )
        )
    if form:
        score = _similar(onboarding.legal_name, form.get("legal_name"))
        checks.append(
            _check(
                "name_matches_form",
                "Legal name matches the tax form",
                "pass" if score >= NAME_MATCH else "warn",
                f"Portal: {onboarding.legal_name}; form: {form.get('legal_name') or '-'}.",
                clearable=True,
            )
        )
    else:
        checks.append(
            _check(
                "tax_id_matches_form",
                "Tax ID matches the tax form",
                "unknown",
                "The tax form couldn't be read: compare it by eye.",
                clearable=True,
            )
        )

    if re.fullmatch(r"\d{9}", routing):
        ok = aba_valid(routing)
        checks.append(
            _check(
                "routing_checksum",
                "Routing number is a valid US ABA number",
                "pass" if ok else "fail",
                "Checksum OK." if ok else "Checksum fails: a digit is wrong.",
            )
        )
    else:
        checks.append(
            _check(
                "routing_checksum",
                "Routing number",
                "warn",
                "Not a 9-digit US routing number: check the format for the bank's country.",
                clearable=True,
            )
        )

    letter = extraction.get("bank_letter")
    letter_acc = documents.digits(letter.get("account_number")) if letter else ""
    letter_rt = documents.digits(letter.get("routing_number")) if letter else ""
    if letter and not letter_acc:
        # Read, but no account number found on it: nothing to compare, a person looks
        checks.append(
            _check(
                "bank_matches_letter",
                "Account and routing numbers match the bank letter",
                "unknown",
                "No account number could be read on the bank letter: compare it by eye.",
                clearable=True,
            )
        )
    elif letter:
        # A conflict (both stated, different) fails; a routing number the letter omits is
        # checked by eye
        same_acc = letter_acc == documents.digits(account)
        same_rt = not letter_rt or letter_rt == documents.digits(routing)
        unverified = (
            ""
            if letter.get("verified") and letter_rt
            else " (read from an image: confirm by eye)"
            if not letter.get("verified")
            else " (the letter states no routing number: confirm it by eye)"
        )
        checks.append(
            _check(
                "bank_matches_letter",
                "Account and routing numbers match the bank letter",
                ("pass" if not unverified else "warn") if same_acc and same_rt else "fail",
                (
                    f"Same as the letter{unverified}."
                    if same_acc and same_rt
                    else "The portal's bank details differ from the bank letter"
                    + ("" if same_acc else " (account number)")
                    + ("" if same_rt else " (routing number)")
                    + "."
                ),
                clearable=same_acc and same_rt,
            )
        )
    if letter:
        score = _similar(
            onboarding.account_name or onboarding.legal_name, letter.get("account_name")
        )
        checks.append(
            _check(
                "account_holder",
                "Account holder is the vendor",
                "pass" if score >= NAME_MATCH else "warn",
                f"Letter: {letter.get('account_name') or '-'}; vendor: {onboarding.legal_name}.",
                clearable=True,
            )
        )
        if letter.get("on_bank_letterhead") is False:
            checks.append(
                _check(
                    "letterhead",
                    "Bank letter on the bank's letterhead",
                    "warn",
                    "It doesn't look like the bank's letterhead.",
                    clearable=True,
                )
            )
    else:
        checks.append(
            _check(
                "bank_matches_letter",
                "Bank details match the bank letter",
                "unknown",
                "The bank letter couldn't be read: compare it by eye.",
                clearable=True,
            )
        )

    hits = await sanctions.screen(session, [onboarding.vendor_name, onboarding.legal_name or ""])
    if hits is None:
        checks.append(
            _check(
                "sanctions",
                "Sanctions screening (OFAC SDN)",
                "fail",
                "No sanctions list loaded: load it in Finance POD settings, then re-run the agent.",
            )
        )
    elif hits:
        checks.append(
            _check(
                "sanctions",
                "Sanctions screening (OFAC SDN)",
                "fail",
                "Potential match: "
                + "; ".join(
                    f"{h.name} ({h.program or 'program n/a'}, entry {h.list_ref}, "
                    f"similarity {h.score:.0%})"
                    for h in hits[:5]
                )
                + ". Clear it only if it's clearly a different party.",
                clearable=True,
            )
        )
    else:
        info = await sanctions.info(session)
        checks.append(
            _check(
                "sanctions",
                "Sanctions screening (OFAC SDN)",
                "pass",
                f"No match among {info.entries:,} entries (list of {info.loaded_at}).",
            )
        )

    onboarding.extraction = extraction
    onboarding.checks = checks


def open_issues(onboarding: FpOnboarding) -> list[Check]:
    """Checks that still stop verification (failed, or warnings nobody cleared)."""
    cleared = {c["key"] for c in onboarding.cleared}
    return [
        c
        for c in onboarding.checks or []
        if c["status"] in ("fail", "warn", "unknown") and c["key"] not in cleared
    ]
