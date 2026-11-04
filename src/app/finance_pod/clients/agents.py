"""The receivables agents of AR Phase 1.

Onboarding agent (1.1.2): reads the client's documents (AI, vision for scans) and checks
them against the application: documents present, tax ID format and match, legal name,
the credit report's age, and the sanctions screen. What only the client can fix becomes a
gap the client is sent; what a person must judge waits for client services.

Credit agent (1.2.1): scores the risk from the credit report, trade references and the
application, and proposes a limit or deposit-only, terms and currency, with its reasons.
The score is computed, never the model's opinion; it only ever proposes.

Monitor (1.3.2): reviews each account as its billing and payment history builds, and when
it is due for its periodic review; it proposes changes for the credit controller.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from difflib import SequenceMatcher
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from src.app.common.clock import utcnow
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.finance_pod import documents
from src.app.finance_pod.clients.models import (
    ClientDocumentKind,
    FpClient,
    FpClientApplication,
    FpClientDocument,
    FpClientHistory,
)
from src.app.finance_pod.onboarding import sanctions
from src.app.service_pod.common import ai

PROMPT_VERSION = "fpod_client_onboarding/v1"
EIN = re.compile(r"^\d{2}-?\d{7}$")
NAME_MATCH = 0.85
REPORT_MAX_AGE_DAYS = 365
REQUIRED = (ClientDocumentKind.REGISTRATION, ClientDocumentKind.TAX)
DOC_LABEL = {
    ClientDocumentKind.REGISTRATION: "business registration",
    ClientDocumentKind.TAX: "tax document",
    ClientDocumentKind.CREDIT_REPORT: "credit report",
    ClientDocumentKind.TRADE_REFERENCE: "trade reference",
    ClientDocumentKind.OTHER: "other document",
}

SYSTEM = """\
You read a document a company sent with its application for a client account: a business
registration (certificate of incorporation), a tax document (W-9 or a tax registration),
a credit report from a credit bureau, or a trade reference letter from one of its
suppliers. Report only what the document states; null otherwise. Write numbers and IDs
exactly as printed. Never guess a digit you can't read.
"""


class ClientDocRead(BaseModel):
    document_type: Literal["registration", "tax", "credit_report", "trade_reference", "other"]
    company_name: str | None = Field(description="The company the document is about")
    registration_number: str | None
    tax_id: str | None = Field(description="EIN / tax registration number as printed")
    address: str | None
    incorporated_on: str | None = Field(description="Date of incorporation, YYYY-MM-DD")
    # Credit report
    bureau: str | None = Field(description="Credit bureau, e.g. Dun & Bradstreet, Experian")
    report_date: str | None = Field(description="Date of the report, YYYY-MM-DD")
    credit_score: int | None = Field(description="The bureau's credit/payment score")
    score_max: int | None = Field(description="Top of that score's scale, e.g. 100")
    risk_rating: str | None = Field(description="The bureau's risk rating or class as printed")
    recommended_limit: str | None = Field(description="Recommended credit limit as printed")
    days_beyond_terms: int | None = Field(description="Average days paid beyond terms")
    legal_filings: int | None = Field(description="Judgments, liens, bankruptcies on file")
    years_in_business: int | None
    # Trade reference
    referee: str | None = Field(description="The supplier giving the reference")
    relationship_years: int | None
    payment_behaviour: Literal["prompt", "slow", "poor"] | None


Check = dict[str, Any]  # {key, label, status: pass|fail|warn|unknown, detail, clearable, gap}


def _check(
    key: str,
    label: str,
    status: str,
    detail: str,
    *,
    clearable: bool = False,
    gap: str | None = None,
) -> Check:
    """`gap`: what the client is asked to fix (only the client can), sent to them."""
    return {
        "key": key,
        "label": label,
        "status": status,
        "detail": detail,
        "clearable": clearable,
        "gap": gap,
    }


def similar(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, sanctions.normalize(a), sanctions.normalize(b)).ratio()


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def amount(value: str | None) -> Decimal | None:
    """A figure as printed ('USD 75,000', '$75k') as a number; None if it isn't one."""
    if not value:
        return None
    text = value.lower().replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(k|m)?", text)
    if not match:
        return None
    n = Decimal(match.group(1))
    return n * {"k": 1000, "m": 1_000_000}.get(match.group(2) or "", 1)


async def _read(
    llm: LLMProvider, doc: FpClientDocument
) -> tuple[dict[str, Any] | None, str | None]:
    prepared = documents.prepare(doc.content, doc.filename)
    if not prepared.readable:
        return None, f"{doc.filename} can't be read ({prepared.problem})"
    stated = documents.digits(prepared.text) if prepared.text else ""

    def problems(r: ClientDocRead) -> list[str]:
        if not prepared.text:
            return []
        return [
            f"{label} {value} isn't in the document's text"
            for label, value in (
                ("tax ID", r.tax_id),
                ("registration number", r.registration_number),
                ("recommended limit", r.recommended_limit),
            )
            if value and documents.digits(value) and documents.digits(value) not in stated
        ]

    try:
        result = await ai.extract(
            llm,
            system=SYSTEM,
            user=(
                f"The document ({doc.filename}, sent as the {DOC_LABEL[doc.kind]}):\n\n"
                f"{prepared.text}"
                if prepared.text
                else f"The document ({doc.filename}, sent as the {DOC_LABEL[doc.kind]}) "
                "is in the images."
            ),
            schema=ClientDocRead,
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
        "kind": doc.kind.value,
        "verified": bool(prepared.text),
        "filename": doc.filename,
        "provenance": result.provenance.as_dict(),
    }, None


async def latest_documents(
    session: AsyncSession, app: FpClientApplication, *, content: bool = False
) -> list[FpClientDocument]:
    """The documents in force: the latest of each kind, and every trade reference."""
    query = select(FpClientDocument).where(FpClientDocument.application_id == app.id)
    if content:
        query = query.options(undefer(FpClientDocument.content))
    docs = list(await session.scalars(query.order_by(FpClientDocument.created_at.desc())))
    seen: set[ClientDocumentKind] = set()
    kept = []
    for d in docs:
        if d.kind == ClientDocumentKind.TRADE_REFERENCE or d.kind not in seen:
            kept.append(d)
            seen.add(d.kind)
    order = list(ClientDocumentKind)
    return sorted(kept, key=lambda d: (order.index(d.kind), d.created_at, d.filename))


async def onboard(session: AsyncSession, llm: LLMProvider, app: FpClientApplication) -> None:
    """Read the documents and run the checks (1.1.2.a-b); stores both, and the gaps for the
    client (1.1.2.c), on the application."""
    docs = await latest_documents(session, app, content=True)
    extraction: dict[str, Any] = {"notes": [], "documents": []}
    reads: dict[ClientDocumentKind, list[dict[str, Any]]] = {}
    for doc in docs:
        read, problem = await _read(llm, doc)
        if read:
            extraction["documents"].append(read)
            reads.setdefault(doc.kind, []).append(read)
        if problem:
            extraction["notes"].append(problem)
    kinds = {d.kind for d in docs}
    checks: list[Check] = []

    missing = [DOC_LABEL[k] for k in REQUIRED if k not in kinds]
    checks.append(
        _check(
            "documents",
            "Business registration and tax document received",
            "fail" if missing else "pass",
            f"Missing: {', '.join(missing)}." if missing else "Both received.",
            gap=f"Please upload your {' and '.join(missing)}." if missing else None,
        )
    )
    unreadable = [n for n in extraction["notes"] if "can't be read" in n]
    if unreadable:
        checks.append(
            _check(
                "readable",
                "Documents can be read",
                "fail",
                "; ".join(unreadable) + ".",
                clearable=True,
                gap="We couldn't read: "
                + ", ".join(n.split(" can't be read")[0] for n in unreadable)
                + ". Please upload a clearer copy (PDF, or a sharp photo).",
            )
        )

    tax_id = (app.tax_id or "").strip()
    if (app.country or "US") == "US":
        ok = bool(EIN.match(tax_id))
        checks.append(
            _check(
                "tax_id_format",
                "Tax ID format (US EIN)",
                "pass" if ok else "fail",
                "Valid format." if ok else f"'{tax_id}' isn't a 9-digit EIN (12-3456789).",
                gap=None if ok else "Your tax ID should be your 9-digit EIN, e.g. 12-3456789.",
            )
        )
    else:
        checks.append(
            _check(
                "tax_id_format",
                "Foreign tax ID",
                "warn" if tax_id else "fail",
                "Foreign tax registration: check it against the tax document."
                if tax_id
                else "No tax ID given.",
                clearable=bool(tax_id),
                gap=None if tax_id else "Please give your company's tax registration number.",
            )
        )

    def first(kind: ClientDocumentKind) -> dict[str, Any] | None:
        found = reads.get(kind)
        return found[0] if found else None

    tax_doc = first(ClientDocumentKind.TAX)
    if tax_doc and documents.digits(tax_doc.get("tax_id")):
        same = documents.digits(tax_doc.get("tax_id")) == documents.digits(tax_id)
        by_eye = "" if tax_doc.get("verified") else " (read from an image: confirm by eye)"
        checks.append(
            _check(
                "tax_id_matches",
                "Tax ID matches the tax document",
                ("pass" if not by_eye else "warn") if same else "fail",
                f"Same as the document{by_eye}."
                if same
                else f"The application says {tax_id or '-'}, the document says "
                f"{tax_doc.get('tax_id')}.",
                clearable=same,
                gap=None
                if same
                else "The tax ID on your application differs from your tax document: please "
                "correct it or upload the right document.",
            )
        )
    elif ClientDocumentKind.TAX in kinds:
        checks.append(
            _check(
                "tax_id_matches",
                "Tax ID matches the tax document",
                "unknown",
                "No tax ID could be read on the tax document: compare it by eye.",
                clearable=True,
            )
        )

    registration = first(ClientDocumentKind.REGISTRATION)
    if registration:
        score = similar(app.legal_name, registration.get("company_name"))
        checks.append(
            _check(
                "name_matches",
                "Legal name matches the business registration",
                "pass" if score >= NAME_MATCH else "warn",
                f"Application: {app.legal_name}; registration: "
                f"{registration.get('company_name') or '-'}.",
                clearable=True,
            )
        )

    report = first(ClientDocumentKind.CREDIT_REPORT)
    if ClientDocumentKind.CREDIT_REPORT not in kinds:
        checks.append(
            _check(
                "credit_report",
                "Credit report",
                "warn",
                "None sent: the credit agent can only propose deposit-only terms.",
                clearable=True,
            )
        )
    elif report:
        on = _date(report.get("report_date"))
        if on is None:
            checks.append(
                _check(
                    "credit_report",
                    "Credit report is recent",
                    "unknown",
                    "The report's date couldn't be read: check it by eye.",
                    clearable=True,
                )
            )
        else:
            age = (utcnow().date() - on).days
            fresh = age <= REPORT_MAX_AGE_DAYS
            checks.append(
                _check(
                    "credit_report",
                    "Credit report is recent",
                    "pass" if fresh else "warn",
                    f"{report.get('bureau') or 'Report'} of {on.isoformat()} ({age} days old)."
                    + ("" if fresh else " Older than a year."),
                    clearable=True,
                    gap=None
                    if fresh
                    else "Your credit report is over a year old: please upload a current one.",
                )
            )

    names = [app.client_name, app.legal_name or ""]
    if registration and registration.get("company_name"):
        names.append(registration["company_name"])
    hits = await sanctions.screen(session, names)
    if hits is None:
        checks.append(
            _check(
                "sanctions",
                "Sanctions screening (OFAC SDN)",
                "fail",
                "No sanctions list loaded: load it on the Vendors page, then re-run the agent.",
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

    app.extraction = extraction
    app.checks = checks
    app.gaps = [c["gap"] for c in checks if c.get("gap")]


def open_issues(app: FpClientApplication) -> list[Check]:
    """Checks that still stop the credit assessment (failed, or warnings nobody cleared)."""
    cleared = {c["key"] for c in app.cleared}
    return [
        c
        for c in app.checks or []
        if c["status"] in ("fail", "warn", "unknown") and c["key"] not in cleared
    ]


# --- the credit agent (1.2.1) --------------------------------------------------------------


def _round_down(value: Decimal, step: int = 500) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def _terms_days(terms: str | None) -> int | None:
    match = re.search(r"net\s*(\d+)", terms or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def assess(app: FpClientApplication, max_new_limit: Decimal) -> dict[str, Any]:
    """Score the risk and propose terms, from the facts the onboarding agent read."""
    reads = (app.extraction or {}).get("documents", [])
    report = next((r for r in reads if r["kind"] == "credit_report"), None)
    refs = [r for r in reads if r["kind"] == "trade_reference"]
    factors: list[dict[str, Any]] = []

    def factor(label: str, value: str, points: int, top: int) -> None:
        factors.append({"label": label, "value": value, "points": points, "max": top})

    reasons: list[str] = []
    if report and report.get("credit_score") is not None:
        top = report.get("score_max") or 100
        pts = round(40 * max(0, min(report["credit_score"], top)) / top)
        factor("Bureau score", f"{report['credit_score']} of {top}", pts, 40)
    else:
        factor("Bureau score", "no credit report", 0, 40)
    dbt = report.get("days_beyond_terms") if report else None
    pts = 8 if dbt is None else 20 if dbt <= 5 else 12 if dbt <= 15 else 5 if dbt <= 30 else 0
    factor("Pays others", "unknown" if dbt is None else f"{dbt} days beyond terms", pts, 20)
    filings = report.get("legal_filings") if report else None
    pts = 7 if filings is None else 15 if filings == 0 else 7 if filings == 1 else 0
    factor("Legal filings", "unknown" if filings is None else str(filings), pts, 15)
    years = (report.get("years_in_business") if report else None) or app.years_trading
    pts = 5 if years is None else 15 if years >= 5 else 10 if years >= 2 else 3
    factor("Years trading", "unknown" if years is None else str(years), pts, 15)
    pts = sum(
        {"prompt": 5, "slow": 2, "poor": -5}.get(r.get("payment_behaviour") or "", 0) for r in refs
    )
    factor(
        "Trade references",
        ", ".join(
            f"{r.get('referee') or 'reference'}: {r.get('payment_behaviour') or 'n/a'}"
            for r in refs
        )
        or "none",
        max(-10, min(pts, 10)),
        10,
    )
    score = max(0, min(100, sum(f["points"] for f in factors)))
    risk = "low" if score >= 70 else "medium" if score >= 50 else "high"
    currency = app.currency or "USD"

    requested = app.requested_limit or (app.expected_monthly * 2 if app.expected_monthly else None)
    recommended = amount(report.get("recommended_limit")) if report else None
    caps = [c for c in (requested, recommended, max_new_limit) if c is not None]
    base = min(caps) if caps else max_new_limit
    asked_days = _terms_days(app.requested_terms)

    decision: str
    limit: Decimal | None
    deposit = Decimal("0")
    if report is None:
        decision, limit, deposit, terms = "deposit", None, Decimal("50"), "Due on receipt"
        reasons.append("No credit report: a new client starts on a deposit until history builds.")
    elif risk == "high":
        deposit = Decimal("100") if score < 35 else Decimal("50")
        decision, limit, terms = "deposit", None, "Due on receipt"
        reasons.append(f"High risk (score {score} of 100): deposit only, {deposit}% up front.")
    else:
        decision = "credit"
        share = Decimal("1") if risk == "low" else Decimal("0.5")
        limit = _round_down(base * share)
        days = 30 if risk == "low" else 15
        terms = f"Net {min(asked_days, days) if asked_days else days}"
        reasons.append(
            f"{risk.capitalize()} risk (score {score} of 100): credit of {currency} {limit:,.2f}"
            f" on {terms}."
        )
        if limit <= 0:
            decision, limit, deposit, terms = "deposit", None, Decimal("50"), "Due on receipt"
            reasons.append("The limit rounds to nothing: deposit only instead.")
        else:
            limit_why = [
                f"requested {currency} {requested:,.2f}" if requested else None,
                f"the bureau recommends {currency} {recommended:,.2f}" if recommended else None,
                f"new clients are capped at {currency} {max_new_limit:,.2f}",
            ]
            reasons.append(
                "Limit from the lowest of: "
                + "; ".join(w for w in limit_why if w)
                + ("" if risk == "low" else ", halved for medium risk")
                + "."
            )
    if report and report.get("risk_rating"):
        reasons.append(f"Bureau rating: {report['risk_rating']}.")
    if any(r.get("payment_behaviour") == "poor" for r in refs):
        reasons.append("A trade reference reports poor payment.")
    return {
        "score": score,
        "risk": risk,
        "decision": decision,
        "credit_limit": str(limit) if limit is not None else None,
        "deposit_pct": str(deposit),
        "payment_terms": terms,
        "currency": currency,
        "factors": factors,
        "reasons": reasons,
    }


# --- the monitor (1.3.2) -------------------------------------------------------------------


@dataclass
class History:
    invoices: int
    paid: int
    on_time: int
    avg_days_late: float | None
    overdue: int
    overdue_amount: Decimal
    worst_overdue_days: int
    open_balance: Decimal
    months: int
    peak_month: Decimal  # the most billed in one month

    @property
    def on_time_rate(self) -> float | None:
        return self.on_time / self.paid if self.paid else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "invoices": self.invoices,
            "paid": self.paid,
            "on_time_rate": None if self.on_time_rate is None else round(self.on_time_rate, 3),
            "avg_days_late": None if self.avg_days_late is None else round(self.avg_days_late, 1),
            "overdue": self.overdue,
            "overdue_amount": str(self.overdue_amount),
            "worst_overdue_days": self.worst_overdue_days,
            "open_balance": str(self.open_balance),
            "months": self.months,
            "peak_month": str(self.peak_month),
        }


def history(rows: list[FpClientHistory], today: date) -> History:
    paid = [r for r in rows if r.paid_on]
    late = [max(0, (r.paid_on - r.due_on).days) for r in paid if r.paid_on]
    open_rows = [r for r in rows if not r.paid_on]
    overdue = [r for r in open_rows if r.due_on < today]
    by_month: dict[tuple[int, int], Decimal] = {}
    for r in rows:
        key = (r.issued_on.year, r.issued_on.month)
        by_month[key] = by_month.get(key, Decimal("0")) + r.amount
    first = min((r.issued_on for r in rows), default=today)
    return History(
        invoices=len(rows),
        paid=len(paid),
        on_time=sum(1 for d in late if d == 0),
        avg_days_late=sum(late) / len(late) if late else None,
        overdue=len(overdue),
        overdue_amount=sum((r.amount for r in overdue), Decimal("0")),
        worst_overdue_days=max(((today - r.due_on).days for r in overdue), default=0),
        open_balance=sum((r.amount for r in open_rows), Decimal("0")),
        months=(today.year - first.year) * 12 + today.month - first.month,
        peak_month=max(by_month.values(), default=Decimal("0")),
    )


def review(
    client: FpClient, h: History, today: date
) -> tuple[str, dict[str, Any], list[str]] | None:
    """A proposed change of terms (trigger, proposed terms, reasons), or None."""
    cur = client.currency
    rate = h.on_time_rate
    current = {
        "status": client.status.value,
        "credit_limit": str(client.credit_limit) if client.credit_limit is not None else None,
        "deposit_pct": str(client.deposit_pct),
        "payment_terms": client.payment_terms,
    }
    if h.worst_overdue_days > 60 or (
        client.credit_limit and h.overdue_amount > client.credit_limit / 2
    ):
        return (
            "history",
            {**current, "status": "on_hold", "deposit_pct": "50.00"},
            [
                f"{h.overdue} invoice(s) overdue, {cur} {h.overdue_amount:,.2f}; the oldest "
                f"{h.worst_overdue_days} days past due.",
                "Hold: new work against a 50% deposit until it's cleared.",
            ],
        )
    if (
        client.credit_limit
        and rate is not None
        and h.paid >= 3
        and (rate < 0.6 or (h.avg_days_late or 0) > 20)
    ):
        lower = _round_down(client.credit_limit / 2)
        return (
            "history",
            {**current, "credit_limit": str(lower)},
            [
                f"Paid on time {rate:.0%} of the time, {h.avg_days_late:.0f} days late on average.",
                f"Lower the limit to {cur} {lower:,.2f}.",
            ],
        )
    good = rate is not None and rate >= 0.9 and h.overdue == 0 and h.months >= 6 and h.paid >= 6
    if client.credit_limit is None and good:
        limit = _round_down(h.peak_month * 2)
        if limit > 0:
            return (
                "history",
                {
                    **current,
                    "status": "active",
                    "credit_limit": str(limit),
                    "deposit_pct": "0.00",
                    "payment_terms": "Net 30",
                },
                [
                    f"{h.months} months of history, {h.paid} invoices paid, {rate:.0%} on time, "
                    "nothing overdue.",
                    f"Move from deposit to credit: {cur} {limit:,.2f} (twice the busiest month) "
                    "on Net 30.",
                ],
            )
    if client.credit_limit and good and h.open_balance >= client.credit_limit * Decimal("0.8"):
        higher = _round_down(client.credit_limit * Decimal("1.5"))
        return (
            "history",
            {**current, "credit_limit": str(higher)},
            [
                f"Using {h.open_balance / client.credit_limit:.0%} of the limit while paying on "
                f"time {rate:.0%} of the time.",
                f"Raise the limit to {cur} {higher:,.2f}.",
            ],
        )
    if client.next_review_on and client.next_review_on <= today:
        return (
            "periodic",
            current,
            [
                "Periodic review due: "
                + (
                    f"{h.invoices} invoices, {rate:.0%} paid on time."
                    if rate is not None
                    else "no billing history yet."
                ),
                "Confirm the current terms (or change them).",
            ],
        )
    return None
