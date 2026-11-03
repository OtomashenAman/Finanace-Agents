"""The agents of a client account set-up: the onboarding agent (1.1.2) reads the client's
documents, screens the names and flags gaps back to the client; the credit agent (1.2.1)
scores the risk and proposes a limit or deposit; the account agent (1.3.1) checks the client
was created in the ERP as approved; the monitor (1.3.2) reviews the limit as history builds.
Pure code on the case's data and snapshot: no figure is invented."""

from __future__ import annotations

import difflib
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import undefer

from src.app.auth.security import create_purpose_token
from src.app.common.clock import utcnow
from src.app.common.text_extraction.base import ExtractionError
from src.app.common.text_extraction.registry import extract_text
from src.app.core.config import get_settings
from src.app.finance_pod import sanctions
from src.app.finance_pod.common import cents, doc_of, draft_once, is_sent, need, policy_of, result
from src.app.finance_pod.flows.ap_vendor_onboarding import reading
from src.app.finance_pod.flows.ar_client_account.policy import ArcPolicy
from src.app.finance_pod.flows.ar_client_account.results import (
    Application,
    ClientCreated,
    CreditDecision,
    CreditProposal,
    DocumentsChecked,
    DocumentsUploaded,
    Gaps,
    InSync,
    LimitReview,
    RiskFactor,
    RiskScore,
    SanctionsHit,
    Screening,
)
from src.app.service_pod.core.cases.models import PodReviewTask, ReviewTaskKind
from src.app.service_pod.core.messaging.models import Audience, PodArtifact
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import Client, SnapshotDocument
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec, Unready
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

Results = dict[str, BaseModel]
PORTAL = "client_portal"
INVITE, GAPS = "client_invite", "client_gaps"
SCREENING = "Sanctions screening"


def portal_link(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/client/{token}"


def issue_link(c: Ctx) -> tuple[str, datetime]:
    """A new signed link for this case (the previous one stops working)."""
    days = policy_of(c.case, ArcPolicy).portal_link_days
    jti = uuid.uuid4().hex
    expires = utcnow() + timedelta(days=days)
    token = create_purpose_token(PORTAL, {"case": str(c.case.id), "jti": jti}, timedelta(days=days))
    c.case.state = {**c.case.state, "portal": {"jti": jti, "expires_at": expires.isoformat()}}
    return token, expires


async def invite(c: Ctx) -> str:
    """Draft the portal invitation (a person sends it): the form and the documents."""
    name = str(c.case.selection["client_name"])
    email = str(c.case.selection["contact_email"])
    token, expires = issue_link(c)
    await draft_once(
        c, purpose=INVITE, audience=Audience.INVITE, to_email=email, to_name=name,
        subject="Open your account with us: application and documents",
        body=(f"Hello,\n\nTo open an account for {name}, please complete the application and "
              f"upload your documents on our secure page:\n\n{portal_link(token)}\n\n"
              "- Your tax form (W-9, or W-8BEN-E outside the US)\n- Your company registration "
              "or other compliance papers\n- Trade references, if you'd like credit terms\n\n"
              f"The link works until {expires:%d %b %Y}.\n\nThank you."),
    )  # fmt: skip
    return email


# --- 1.1.2 Onboarding agent ---------------------------------------------------------------


async def _documents(c: Ctx, ids: list[uuid.UUID]) -> list[PodArtifact]:
    if not ids:
        return []
    return list(
        await c.session.scalars(
            select(PodArtifact)
            .options(undefer(PodArtifact.content))
            .where(PodArtifact.case_id == c.case.id, PodArtifact.id.in_(ids))
        )
    )


def _text(doc: PodArtifact) -> str:
    try:
        return extract_text(doc.content, doc.filename).text
    except ExtractionError:
        return ""


def _alike(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    x, y = sanctions.normalize(a), sanctions.normalize(b)
    return x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.85


def _digits(value: str | None) -> str:
    return "".join(ch for ch in value or "" if ch.isalnum()).upper()


async def ready_to_onboard(c: Ctx) -> Unready | None:
    """An application entered in the app (on paper, by a credit controller) must be complete
    before the agent reads it: what's missing is fixed in 1.1.1, not emailed to the client.
    One the client sent through the portal is read as it is (gaps go back to the client)."""
    rows = [r for r in c.children.steps if r.l5_code == "1.1.1.a"]
    if not rows or rows[0].done_by is None:  # the client, through the portal
        return None
    app = result(c, "1.1.1.a", Application)
    docs = result(c, "1.1.1.b", DocumentsUploaded)
    if app is None or docs is None:
        return None
    policy = policy_of(c.case, ArcPolicy)
    fill: list[str] = []
    if docs.tax_form_id is None:
        fill.append("choose the tax form (add it under Documents first)")
    if not docs.registration_ids:
        fill.append("tick the registration papers (add them under Documents first)")
    if app.requested_limit > 0 and len(app.trade_references) < policy.references_for_credit:
        fill.append(
            f"add {policy.references_for_credit} trade references, or set the credit "
            "requested to 0 to start on deposit"
        )
    if not fill:
        return None
    return Unready(message="; ".join(fill) + ".", fix_step="1.1.1")


async def onboard(c: Ctx, step: StepSpec) -> Results:
    """1.1.2: the tax form against the application, the sanctions screen, and the gaps (if
    any, an email to the client is drafted and the step waits for them)."""
    app = need(c, "1.1.1.a", Application)
    docs = need(c, "1.1.1.b", DocumentsUploaded)
    policy = policy_of(c.case, ArcPolicy)
    gaps: list[str] = []

    found = await _documents(c, [docs.tax_form_id]) if docs.tax_form_id else []
    tax_doc = found[0] if found else None
    tax = reading.read_tax_form(_text(tax_doc)) if tax_doc else None
    if tax_doc is None:
        gaps.append("the tax form (W-9, or W-8BEN-E outside the US) isn't uploaded")
    elif tax is None:
        gaps.append("the tax form can't be read (a scan without text): upload a text PDF")
    name_ok = bool(tax) and (_alike(tax.legal_name, app.legal_name) if tax else False)
    tin_ok = (
        bool(tax)
        and bool(tax and tax.tax_id)
        and _digits(tax.tax_id if tax else "") == (_digits(app.tax_id))
    )
    checks = reading.check_tax_id(tax) if tax else []
    if tax and not name_ok:
        gaps.append(f"the name on the tax form ({tax.legal_name}) differs from {app.legal_name}")
    if tax and tax.tax_id and not tin_ok:
        gaps.append("the tax ID on the tax form differs from the one in the application")
    gaps.extend(f"tax ID: {problem}" for problem in checks)
    registration = await _documents(c, docs.registration_ids)
    if not registration:
        gaps.append("no company registration or compliance document is uploaded")
    if app.requested_limit > 0 and len(app.trade_references) < policy.references_for_credit:
        gaps.append(
            f"credit was requested with {len(app.trade_references)} trade reference(s); "
            f"{policy.references_for_credit} are needed (or apply on deposit)"
        )

    loaded = await sanctions.current(c.session)
    if loaded is None:
        raise StepFailedError(
            "The OFAC sanctions list isn't loaded yet (daily job, or Admin → Finance POD): a "
            "client is never passed unscreened."
        )
    names = [n for n in (c.case.selection["client_name"], app.legal_name, app.trading_name) if n]
    names = list(dict.fromkeys(names))
    hits = await sanctions.screen(c.session, names, policy.sanctions_match_threshold)
    if hits and not any(t.subject == SCREENING for t in c.children.review_tasks):
        task = PodReviewTask(
            case_id=c.case.id, kind=ReviewTaskKind.OTHER, subject=SCREENING,
            detail="Possible OFAC SDN match: " + "; ".join(
                f"{h.screened_name} ~ {h.listed_name} (entry {h.entry_id}, "
                f"{h.programs or 'n/a'}, score {h.score})" for h in hits
            ) + ". Clear it with the evidence, or decline the account.",
            blocking=True, created_by=None,
        )  # fmt: skip
        c.session.add(task)
        c.children.review_tasks.append(task)

    if gaps:
        c.case.state = {**c.case.state, "_gaps_flagged": True}
        token, _ = issue_link(c)
        listed = "\n".join(f"- {g[0].upper()}{g[1:]}" for g in gaps)
        message = await draft_once(
            c, purpose=GAPS, audience=Audience.INVITE, to_email=c.case.selection["contact_email"],
            to_name=app.legal_name,
            subject="Your account application: a few things are missing",
            body=(f"Hello,\n\nThank you for your application for {app.legal_name}. Before we "
                  f"can decide on it we need:\n\n{listed}\n\nPlease add them on the same secure "
                  f"page:\n\n{portal_link(token)}\n\nThank you."),
        )  # fmt: skip
        state = "sent" if is_sent(message) else "drafted: review and send it"
        raise StepFailedError(
            f"{len(gaps)} gap(s) to flag to the client ({'; '.join(gaps)}). The email is "
            f"{state}; run this step again once the client has fixed them."
        )
    return {
        "1.1.2.a": DocumentsChecked(
            tax_form=tax.form if tax else "missing",
            name_on_form=tax.legal_name if tax else None,
            tax_id_on_form=reading.mask(tax.tax_id) if tax else None,
            name_matches=name_ok, tax_id_matches=tin_ok, tax_id_checks=checks,
            registration_documents=len(registration),
        ),
        "1.1.2.b": Screening(
            sanctions_list=f"{loaded.list_name} ({loaded.entries} entries)",
            sanctions_loaded_at=loaded.created_at, screened=names,
            hits=[SanctionsHit(**h.__dict__) for h in hits],
            not_checked="IRS TIN matching and credit bureau reports (not connected)",
        ),
        "1.1.2.c": Gaps(gaps=[]),
    }  # fmt: skip


# --- 1.2.1 Credit agent ---------------------------------------------------------------------


def _same_client(doc: SnapshotDocument, app: Application) -> Client | None:
    """An existing client with the same tax ID or name (the books' history applies)."""
    tin = _digits(app.tax_id)
    for client in doc.clients or []:
        if (tin and _digits(client.tax_id) == tin) or _alike(client.name, app.legal_name):
            return client
    return None


def payment_history(doc: SnapshotDocument, client_id: str, today: date) -> tuple[int, int, int]:
    """(invoices paid, of them late, oldest open item's days overdue) from the books."""
    invoices = [i for i in doc.sales_invoices or [] if i.client_id == client_id
                and i.doc_status == "Submitted" and i.return_against is None]  # fmt: skip
    paid_on: dict[str, date] = {}
    for pay in doc.client_payments or []:
        for alloc in pay.allocations:
            paid_on[alloc.invoice_id] = max(paid_on.get(alloc.invoice_id, pay.date), pay.date)
    paid = [i for i in invoices if i.outstanding == 0]
    late = [i for i in paid if i.due_date and i.id in paid_on and paid_on[i.id] > i.due_date]
    overdue = [
        (today - i.due_date).days for i in invoices
        if i.outstanding > 0 and i.due_date and i.due_date < today
    ]  # fmt: skip
    return len(paid), len(late), max(overdue, default=0)


async def score(c: Ctx, step: StepSpec) -> Results:
    """1.2.1: a risk score from the application, the documents, the screening and (for a
    client the books already know) the payment history; then a limit or a deposit."""
    app = need(c, "1.1.1.a", Application)
    checked = need(c, "1.1.2.a", DocumentsChecked)
    screening = need(c, "1.1.2.b", Screening)
    policy = policy_of(c.case, ArcPolicy)
    doc = await doc_of(c)
    today = utcnow().date()
    factors = [RiskFactor(factor="starting point", points=50)]

    def add(factor: str, points: int) -> None:
        factors.append(RiskFactor(factor=factor, points=points))

    if checked.name_matches and checked.tax_id_matches:
        add("tax form matches the application", 10)
    refs = len(app.trade_references)
    if refs:
        add(f"{refs} trade reference(s)", min(refs, 3) * 5)
    else:
        add("no trade references", -10)
    if app.established_year:
        years = today.year - app.established_year
        add(f"established {years} year(s)", 10 if years >= 5 else 5 if years >= 2 else -5)
    if app.country.strip().casefold() != policy.home_country.casefold():
        add(f"outside {policy.home_country}", -5)
    if screening.hits:
        add("possible sanctions match (review task)", -40)
    known = _same_client(doc, app)
    history = "new to the books: no payment history"
    if known is not None:
        paid, late, overdue = payment_history(doc, known.id, today)
        history = (f"already in the books as {known.id}: {paid} invoice(s) paid, {late} late; "
                   f"oldest open item {overdue} day(s) overdue")  # fmt: skip
        add("paid on time" if paid and not late else f"{late} late payment(s)",
            10 if paid and not late else -10 * min(late, 3))  # fmt: skip
        if overdue > policy.review_overdue_days:
            add(f"an item {overdue} days overdue", -20)
    if app.requested_limit > policy.low_risk_limit:
        add("asks for more than the largest limit given", -10)
    total = max(0, min(100, sum(f.points for f in factors)))
    band = (
        "low" if total >= policy.low_risk_from
        else "medium" if total >= policy.medium_risk_from else "high"
    )  # fmt: skip

    terms = min((d for d in policy.terms_days if d >= app.requested_terms_days),
                default=max(policy.terms_days))  # fmt: skip
    terms = min(terms, policy.default_terms_days) if terms else terms
    cap = {"low": policy.low_risk_limit, "medium": policy.medium_risk_limit}.get(band)
    version = c.case.state.get("policy", {}).get("version", "")
    if app.requested_limit == 0 or cap is None or refs < policy.references_for_credit:
        why = (
            "the client applied to pay on deposit" if app.requested_limit == 0
            else f"risk is {band} ({total})" if cap is None
            else f"{refs} of {policy.references_for_credit} trade references"
        )  # fmt: skip
        proposal = CreditProposal(
            deposit_only=True, credit_limit=None, terms_days=0, deposit_pct=policy.deposit_pct,
            reason=f"Start on deposit (AR1.R2): {why}.", policy_version=version,
        )  # fmt: skip
    else:
        limit = cents(min(app.requested_limit, cap))
        proposal = CreditProposal(
            deposit_only=False, credit_limit=limit, terms_days=terms, deposit_pct=None,
            reason=(f"Risk {band} ({total}): up to {cap:,.0f} for this band; requested "
                    f"{app.requested_limit:,.2f}."),
            policy_version=version,
        )  # fmt: skip
    return {
        "1.2.1.a": RiskScore(score=total, band=band, factors=factors, history=history),
        "1.2.1.b": proposal,
    }


# --- 1.3.1 Set up once / 1.3.2 Monitor ---------------------------------------------------


async def customer_task(c: Ctx) -> PodPostingTask | None:
    return await c.session.scalar(
        select(PodPostingTask).where(
            PodPostingTask.case_id == c.case.id,
            PodPostingTask.kind == TaskKind.CREATE_CUSTOMER,
            PodPostingTask.status != TaskStatus.CANCELLED,
        )
    )


async def set_up(c: Ctx, step: StepSpec) -> Results:
    """1.3.1: the client is in the ERP, once, exactly as approved (from the snapshot that
    verified the posting)."""
    task = await customer_task(c)
    if task is None:
        raise StepFailedError("The client isn't queued for the ERP yet (it is on release).")
    if task.status != TaskStatus.VERIFIED or task.verification_snapshot_id is None:
        where = f" as {task.external_txn_id}" if task.external_txn_id else ""
        raise StepFailedError(
            f"The client is {task.status.value.replace('_', ' ')}{where}: post it if needed, "
            "then verify it with a fresh snapshot and run this step again."
        )
    snapshot = await c.session.get(PodSnapshot, task.verification_snapshot_id)
    assert snapshot is not None  # noqa: S101 - verification keeps the snapshot
    client = next(
        (x for x in snapshots.document(snapshot).clients or [] if x.id == task.external_txn_id),
        None,
    )
    if client is None:
        raise StepFailedError("The verifying snapshot doesn't hold the client.")
    decision = need(c, "1.2.2.a", CreditDecision)
    limit = decision.credit_limit if decision.decision == "approve_credit" else None
    terms = decision.terms_days if decision.decision == "approve_credit" else 0
    differences = []
    if (client.credit_limit or None) != (cents(limit) if limit else None):
        differences.append(f"credit limit {client.credit_limit} in the ERP, {limit} approved")
    if client.terms_days is not None and client.terms_days != terms:
        differences.append(f"terms {client.terms_days} days in the ERP, {terms} approved")
    if client.email is None:
        differences.append("no contact email on the client in the ERP")
    if client.status != "Active":
        differences.append(f"the client is {client.status} in the ERP")
    if differences:
        raise StepFailedError("The ERP differs from what was approved: " + "; ".join(differences))
    return {
        "1.3.1.a": ClientCreated(
            erp_customer=client.id, verified_on=f"snapshot of {snapshot.as_of}",
            lab_system="not connected yet: the client is created in the ERP only",
        ),
        "1.3.1.b": InSync(checked=["credit limit", "payment terms", "contact email", "status"],
                          differences=[]),
    }  # fmt: skip


def review(doc: SnapshotDocument, client_id: str, policy: ArcPolicy, today: date) -> LimitReview:
    """A client's limit against what the books show today."""
    client = next((x for x in doc.clients or [] if x.id == client_id), None)
    limit = client.credit_limit if client else None
    outstanding = sum(
        (i.outstanding for i in doc.sales_invoices or []
         if i.client_id == client_id and i.doc_status == "Submitted"),
        Decimal(0),
    )  # fmt: skip
    _, _, overdue = payment_history(doc, client_id, today)
    used = cents(outstanding * 100 / limit) if limit else None
    reasons = []
    if used is not None and used >= policy.review_utilisation_pct:
        reasons.append(f"{used}% of the limit is used")
    if overdue > policy.review_overdue_days:
        reasons.append(f"an item is {overdue} days overdue")
    return LimitReview(
        as_of=doc.as_of, credit_limit=limit, outstanding=cents(outstanding),
        utilisation_pct=used, oldest_overdue_days=overdue,
        suggestion="review" if reasons else "keep",
        reason="; ".join(reasons) or "within the limit and nothing long overdue",
    )  # fmt: skip


async def monitor(c: Ctx, step: StepSpec) -> Results:
    """1.3.2: the first review on the verified client (a daily job reviews it again)."""
    created = need(c, "1.3.1.a", ClientCreated)
    task = await customer_task(c)
    assert task is not None and task.verification_snapshot_id  # noqa: S101 - 1.3.1 checked
    snapshot = await c.session.get(PodSnapshot, task.verification_snapshot_id)
    assert snapshot is not None  # noqa: S101
    found = review(snapshots.document(snapshot), created.erp_customer,
                   policy_of(c.case, ArcPolicy), utcnow().date())  # fmt: skip
    return {"1.3.2.a": found}
