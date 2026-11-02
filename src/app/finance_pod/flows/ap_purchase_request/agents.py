"""The purchase request's agents (AGENT steps). Figures come from the case's snapshot and
deterministic code only; an agent never invents an id, a price or a date. When it can't
finish it says why (the step fails with that reason) and a person reruns it."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select

from src.app.common.clock import utcnow
from src.app.finance_pod.common import (
    cents,
    doc_of,
    draft_once,
    is_sent,
    money_text,
    need,
    policy_of,
    result,
    snapshot_of,
)
from src.app.finance_pod.flows.ap_purchase_request.policy import PrqPolicy
from src.app.finance_pod.flows.ap_purchase_request.results import (
    Acknowledgement,
    BudgetCheck,
    BudgetLine,
    Candidate,
    Coding,
    Comparison,
    DraftPo,
    Excluded,
    GrantCheck,
    MissingData,
    Need,
    PoCoding,
    PoLine,
    PoLineCoding,
    PoSent,
    PriceCheck,
    PricedLine,
    QuoteRequests,
    QuoteRow,
    RfqSent,
    Routing,
    Sourcing,
    VendorChoice,
)
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodCase,
    PodReviewTask,
    ReviewTaskKind,
)
from src.app.service_pod.core.messaging.models import Audience
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec, StepStatus
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

Results = dict[str, BaseModel]
OPEN_PO = ("To Receive and Bill", "To Bill", "To Receive", "On Hold")
OPEN_REQUEST = ("Pending", "Partially Ordered")


def _policy(c: Ctx) -> PrqPolicy:
    return policy_of(c.case, PrqPolicy)


def _contract_rate(doc: SnapshotDocument, item: str, vendor: str) -> Decimal | None:
    return next(
        (p.rate for p in doc.item_prices or [] if p.item_code == item and p.vendor_id == vendor),
        None,
    )


def _catalogue_rate(doc: SnapshotDocument, item: str) -> Decimal | None:
    return next(
        (p.rate for p in doc.item_prices or [] if p.item_code == item and p.vendor_id is None),
        None,
    )


def _active(doc: SnapshotDocument) -> dict[str, str]:
    return {v.id: v.name for v in doc.vendors or [] if v.status == "Active"}


# --- 1.1.2 Request agent enriches ---------------------------------------------------------


def _history(doc: SnapshotDocument, items: set[str]) -> dict[str, str | None]:
    """The coding most often used on earlier orders and requests for these items."""
    seen: dict[str, Counter[str]] = defaultdict(Counter)
    lines = [ln for po in doc.purchase_orders or [] for ln in po.lines] + [
        ln for pr in doc.purchase_requests or [] for ln in pr.lines
    ]
    for ln in lines:
        if ln.item_code in items:
            for field in ("cost_centre_id", "lab_id", "grant_id"):
                value = getattr(ln, field)
                if value:
                    seen[field][value] += 1
    return {f: (seen[f].most_common(1)[0][0] if seen[f] else None) for f in
            ("cost_centre_id", "lab_id", "grant_id")}  # fmt: skip


async def enrich(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    want = need(c, "1.1.1.a", Need)
    items = {i.code: i for i in doc.items or []}
    known = {
        "cost_centre_id": {x.id for x in doc.cost_centres or []},
        "lab_id": {x.id for x in doc.labs or []},
        "grant_id": {x.id for x in doc.grants or []},
    }
    missing: list[str] = []

    history = _history(doc, {ln.item_code for ln in want.lines})
    chosen: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    for field in ("cost_centre_id", "lab_id", "grant_id"):
        given = getattr(want, field)
        label = field.removesuffix("_id").replace("_", " ")
        if given:
            if given not in known[field]:
                missing.append(f"unknown {label} {given!r}")
            chosen[field], sources[field] = given, "requester"
        elif history[field] and field != "grant_id":  # a grant is never assumed
            chosen[field], sources[field] = history[field], "history"
        else:
            chosen[field], sources[field] = None, "none"
    coding = Coding(
        **chosen,
        sources=sources,
        explanation="; ".join(
            f"{f.removesuffix('_id').replace('_', ' ')}: "
            + {
                "requester": "as requested",
                "history": "from earlier orders for these items",
                "none": "not set",
            }[src]
            for f, src in sources.items()
        ),
    )
    if coding.cost_centre_id is None:
        missing.append("cost centre")
    if doc.labs is not None and coding.lab_id is None:
        missing.append("lab")

    priced: list[PricedLine] = []
    for ln in want.lines:
        item = items.get(ln.item_code)
        if item is None:
            missing.append(f"line {ln.item_code}: not a catalogue item")
            continue
        catalogue = _catalogue_rate(doc, item.code)
        contracts = [
            (p.rate, p.vendor_id)
            for p in doc.item_prices or []
            if p.item_code == item.code and p.vendor_id in _active(doc)
        ]
        best = min(contracts, default=None, key=lambda x: x[0])
        if best is not None:
            rate, source, vendor = best[0], "contract", best[1]
        elif catalogue is not None:
            rate, source, vendor = catalogue, "catalogue", None
        elif ln.estimated_unit_price is not None:
            rate, source, vendor = ln.estimated_unit_price, "requester_estimate", None
        else:
            rate, source, vendor = None, "none", None
            missing.append(f"line {item.code}: no price (no contract, catalogue or estimate)")
        variance = None
        if rate and ln.estimated_unit_price is not None:
            variance = cents((ln.estimated_unit_price - rate) / rate * 100)
        priced.append(
            PricedLine(
                item_code=item.code, item_name=item.name, quantity=ln.quantity, unit_rate=rate,
                rate_source=source, contract_vendor_id=vendor, catalogue_rate=catalogue,
                contract_rate=best[0] if best else None, estimate=ln.estimated_unit_price,
                variance_pct=variance, amount=cents(rate * ln.quantity) if rate else None,
                account_id=item.expense_account_id,
            )
        )  # fmt: skip
    total = sum((p.amount for p in priced if p.amount is not None), Decimal(0))
    urgent = want.needed_by < utcnow().date()
    if urgent:
        await _raise_once(
            c,
            "Urgent buy",
            f"Needed by {want.needed_by.isoformat()}, a date already past: the purchase may "
            "have been made before a PO existed. The budget owner confirms how it happened.",
        )
    if missing:
        raise StepFailedError("Missing before submit: " + "; ".join(missing) + ".")
    return {
        "1.1.2.a": coding,
        "1.1.2.b": PriceCheck(lines=priced, total=cents(total), currency=doc.currency),
        "1.1.2.c": MissingData(missing=[], urgent=urgent),
    }


async def _raise_once(c: Ctx, subject: str, detail: str) -> None:
    if any(t.subject == subject for t in c.children.review_tasks):
        return
    task = PodReviewTask(
        case_id=c.case.id, kind=ReviewTaskKind.OTHER, subject=subject, detail=detail,
        blocking=True, created_by=None,
    )  # fmt: skip
    c.session.add(task)
    c.children.review_tasks.append(task)


# --- 1.2.1 Budget agent checks --------------------------------------------------------------


async def _committed_elsewhere(c: Ctx, against: str, target: str, account: str) -> Decimal:
    """Released requests of the same entity whose PO isn't in the source yet."""
    others = list(
        await c.session.scalars(
            select(PodCase).where(
                PodCase.workflow == WorkflowKey.AP_PURCHASE_REQUEST,
                PodCase.entity_id == c.case.entity_id,
                PodCase.status == CaseStatus.APPROVED,
                PodCase.id != c.case.id,
            )
        )
    )
    total = Decimal(0)
    for other in others:
        rows = {
            r.l5_code: r
            for r in await c.session.scalars(
                select(PodCaseStep).where(
                    PodCaseStep.case_id == other.id,
                    PodCaseStep.l5_code.in_(["1.1.2.a", "1.1.2.b", "1.6.1.c"]),
                )
            )
        }
        if "1.6.1.c" in rows and rows["1.6.1.c"].status == StepStatus.DONE:
            continue  # its PO is out: counted from the source once a snapshot holds it
        coding, prices = rows.get("1.1.2.a"), rows.get("1.1.2.b")
        if not (coding and prices and coding.result and prices.result):
            continue
        field = "cost_centre_id" if against == "cost_centre" else "grant_id"
        if coding.result.get(field) != target:
            continue
        total += sum(
            (Decimal(str(ln["amount"])) for ln in prices.result["lines"]
             if ln.get("account_id") == account and ln.get("amount") is not None),
            Decimal(0),
        )  # fmt: skip
    return total


def _committed_in_source(doc: SnapshotDocument, against: str, target: str, account: str) -> Decimal:
    field = "cost_centre_id" if against == "cost_centre" else "grant_id"
    total = Decimal(0)
    for po in doc.purchase_orders or []:
        if po.doc_status != "Submitted" or po.status not in OPEN_PO:
            continue
        for ln in po.lines:
            if getattr(ln, field) == target and ln.account_id == account:
                total += max(ln.amount - ln.billed_amount, Decimal(0))
    items = {i.code: i for i in doc.items or []}
    for pr in doc.purchase_requests or []:
        if pr.doc_status != "Submitted" or pr.status not in OPEN_REQUEST:
            continue
        for rl in pr.lines:
            item = items.get(rl.item_code)
            line_account = rl.account_id or (item.expense_account_id if item else None)
            if getattr(rl, field) == target and line_account == account and rl.rate:
                total += max(rl.qty - rl.ordered_qty, Decimal(0)) * rl.rate
    return cents(total)


async def check_budget(c: Ctx, step: StepSpec) -> Results:
    policy = _policy(c)
    snapshot = await snapshot_of(c)
    age = (utcnow() - snapshot.created_at).total_seconds() / 3600
    if age > policy.budget_data_max_age_hours:
        raise StepFailedError(
            f"The budget figures come from a snapshot taken {age:.0f} hours ago (the limit is "
            f"{policy.budget_data_max_age_hours}): take a fresh ERPNext snapshot and move the "
            "case to it."
        )
    doc = snapshots.document(snapshot)
    want = need(c, "1.1.1.a", Need)
    coding = need(c, "1.1.2.a", Coding)
    prices = need(c, "1.1.2.b", PriceCheck)
    by_account: dict[str, Decimal] = defaultdict(Decimal)
    for ln in prices.lines:
        if ln.amount is not None:
            by_account[ln.account_id or "(no expense account)"] += ln.amount

    targets = [("cost_centre", coding.cost_centre_id)]
    if coding.grant_id:
        targets.append(("grant", coding.grant_id))
    lines: list[BudgetLine] = []
    for against, target in targets:
        assert target is not None  # noqa: S101 - 1.1.2 required a cost centre
        for account, amount in by_account.items():
            budgets = [
                b for b in doc.budgets or []
                if b.against == against and b.target_id == target and b.account_id == account
            ]  # fmt: skip
            budget = sum((b.amount for b in budgets), Decimal(0)) if budgets else None
            actual = sum(
                (a.amount for a in doc.budget_actuals or []
                 if a.against == against and a.target_id == target and a.account_id == account),
                Decimal(0),
            )  # fmt: skip
            committed = _committed_in_source(
                doc, against, target, account
            ) + await _committed_elsewhere(c, against, target, account)
            remaining = None if budget is None else cents(budget - actual - committed - amount)
            lines.append(
                BudgetLine(
                    against=against, target_id=target, account_id=account, budget=budget,
                    actual=cents(actual), committed=cents(committed), this_request=cents(amount),
                    remaining_after=remaining, over=remaining is None or remaining < 0,
                )
            )  # fmt: skip

    grant_check = GrantCheck(grant_id=coding.grant_id, applies=False, allowed=True, problems=[])
    if coding.grant_id:
        grant = next((g for g in doc.grants or [] if g.id == coding.grant_id), None)
        problems: list[str] = []
        today = utcnow().date()
        if grant is None:
            problems.append(f"grant {coding.grant_id} isn't in the source")
        else:
            if grant.status != "Open":
                problems.append(f"the grant is {grant.status}")
            if grant.end_date and grant.end_date < today:
                problems.append(f"the grant ended on {grant.end_date.isoformat()}")
            elif grant.end_date and want.needed_by > grant.end_date:
                problems.append(f"needed after the grant ends ({grant.end_date.isoformat()})")
            if grant.start_date and grant.start_date > today:
                problems.append(f"the grant starts on {grant.start_date.isoformat()}")
            items = {i.code: i for i in doc.items or []}
            if grant.restricted:
                if not grant.allowed_item_groups:
                    problems.append("restricted fund without allowed item groups: ask grants")
                for wanted in want.lines:
                    item = items.get(wanted.item_code)
                    if item and item.group not in grant.allowed_item_groups:
                        problems.append(f"{item.name} ({item.group}) isn't allowed on this grant")
        grant_check = GrantCheck(
            grant_id=coding.grant_id, applies=True, allowed=not problems, problems=problems
        )

    tiers = sorted(policy.authority_tiers, key=lambda t: t.min_amount, reverse=True)
    tier = next((t for t in tiers if prices.total >= t.min_amount), tiers[-1])
    routing = Routing(
        amount=prices.total, tier_from=tier.min_amount, approvers=tier.approvers,
        quotes_required=prices.total >= policy.quote_threshold,
        quote_threshold=policy.quote_threshold,
        po_approval_required=prices.total > policy.po_approval_limit,
        po_approval_limit=policy.po_approval_limit,
    )  # fmt: skip
    return {
        "1.2.1.a": BudgetCheck(
            lines=lines,
            within_budget=all(not ln.over for ln in lines),
            data_as_of=snapshot.created_at.isoformat(),
        ),
        "1.2.1.b": grant_check,
        "1.2.1.c": routing,
    }


# --- 1.3.1 Sourcing agent ---------------------------------------------------------------------


async def find_vendors(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    want = need(c, "1.1.1.a", Need)
    codes = {ln.item_code for ln in want.lines}
    supplied = {po.vendor_id for po in doc.purchase_orders or [] if
                any(ln.item_code in codes for ln in po.lines)} | {
        q.vendor_id for q in doc.supplier_quotations or [] if
        any(ln.item_code in codes for ln in q.lines)}  # fmt: skip
    candidates: list[Candidate] = []
    excluded: list[Excluded] = []
    for v in doc.vendors or []:
        rates = [_contract_rate(doc, ln.item_code, v.id) for ln in want.lines]
        has_contract = any(r is not None for r in rates)
        if not (has_contract or v.id in supplied):
            continue
        if v.status != "Active":
            excluded.append(Excluded(vendor_id=v.id, name=v.name, reason=f"vendor is {v.status}"))
            continue
        total = None
        if all(r is not None for r in rates):
            total = cents(sum((r * ln.quantity for r, ln in zip(rates, want.lines, strict=True)
                               if r is not None), Decimal(0)))  # fmt: skip
        candidates.append(
            Candidate(vendor_id=v.id, name=v.name, has_email=bool(v.email),
                      contract_total=total, supplied_before=v.id in supplied)
        )  # fmt: skip
    candidates.sort(key=lambda x: (x.contract_total is None, x.contract_total or 0, x.name))
    return {"1.3.1.a": Sourcing(candidates=candidates, excluded=excluded)}


async def quotes_not_needed(c: Ctx) -> str | None:
    routing = result(c, "1.2.1.c", Routing)
    if routing is not None and not routing.quotes_required:
        return (
            f"Below the purchasing threshold ({routing.quote_threshold:,.2f}): "
            "the contract or catalogue price applies, no quotes needed"
        )
    return None


async def request_quotes(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    want = need(c, "1.1.1.a", Need)
    routing = need(c, "1.2.1.c", Routing)
    sourcing = need(c, "1.3.1.a", Sourcing)
    emails = {v.id: v.email for v in doc.vendors or []}
    items = {i.code: i for i in doc.items or []}
    lines = "\n".join(
        f"- {items[ln.item_code].name if ln.item_code in items else ln.item_code} "
        f"({ln.item_code}): {ln.quantity.normalize()}"
        for ln in want.lines
    )
    requested: list[RfqSent] = []
    skipped: list[Excluded] = []
    drafts = []
    for cand in sourcing.candidates[: _policy(c).max_rfq_vendors]:
        email = emails.get(cand.vendor_id)
        if not email:
            skipped.append(Excluded(vendor_id=cand.vendor_id, name=cand.name,
                                    reason="no verified email in the vendor master"))  # fmt: skip
            continue
        message = await draft_once(
            c, purpose="rfq", audience=Audience.VENDOR, to_email=email, to_name=cand.name,
            subject=f"Request for quotation {c.case.reference}",
            body=(f"Dear {cand.name},\n\nPlease quote for the following, needed by "
                  f"{want.needed_by.isoformat()}:\n\n{lines}\n\nPlease include unit prices, "
                  f"lead time, validity and terms, and reply to this email.\n\nThank you."),
        )  # fmt: skip
        drafts.append(message)
        requested.append(RfqSent(vendor_id=cand.vendor_id, message_id=message.id))
    unsent = [m for m in drafts if not is_sent(m)]
    if unsent:
        raise StepFailedError(
            f"{len(unsent)} quote request(s) drafted: a buyer reviews and sends them, then "
            "runs this step again."
        )
    return {
        "1.3.1.b": QuoteRequests(
            threshold=routing.quote_threshold, amount=routing.amount, requested=requested,
            skipped=skipped,
        )
    }  # fmt: skip


async def compare_quotes(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    prices = need(c, "1.1.2.b", PriceCheck)
    routing = need(c, "1.2.1.c", Routing)
    vendors = {v.id: v.name for v in doc.vendors or []}
    rows: list[QuoteRow] = []
    erp_request = c.case.selection.get("erp_request_id")
    for q in doc.supplier_quotations or []:
        if not erp_request or q.doc_status != "Submitted":
            continue
        if not any(ln.request_id == erp_request for ln in q.lines):
            continue
        rows.append(
            QuoteRow(
                vendor_id=q.vendor_id, vendor_name=vendors.get(q.vendor_id, q.vendor_id),
                source="erp", reference=q.id, total=q.total,
                lead_time_days=max((ln.lead_time_days or 0 for ln in q.lines), default=None),
                valid_till=q.valid_till, terms=q.terms,
                rates={ln.item_code: ln.rate for ln in q.lines},
            )
        )  # fmt: skip
    for q in c.case.state.get("quotes", []):
        rows.append(QuoteRow.model_validate({**q, "source": "recorded"}))
    required = _policy(c).min_quotes if routing.quotes_required else 0
    if len(rows) < required:
        raise StepFailedError(
            f"{len(rows)} of {required} quotes so far: record the vendors' quotes as they "
            "arrive, then run this step again."
        )
    cheapest = min(rows, key=lambda r: r.total, default=None)
    timed = [r for r in rows if r.lead_time_days is not None]
    fastest = min(timed, key=lambda r: r.lead_time_days or 0, default=None)
    return {
        "1.3.1.c": Comparison(
            quotes=sorted(rows, key=lambda r: r.total), required=required,
            cheapest=cheapest.reference if cheapest else None,
            fastest=fastest.reference if fastest else None, reference_price=prices.total,
        )
    }  # fmt: skip


# --- 1.6.1 PO agent ---------------------------------------------------------------------------


async def chosen_vendor(c: Ctx) -> str:
    """The vendor id the PO goes to: the one chosen, or (a new vendor) the supplier its
    onboarding case created, once the case's snapshot holds it."""
    choice = need(c, "1.3.2.b", VendorChoice)
    if choice.vendor_id:
        return choice.vendor_id
    link = c.case.state.get("vendor_case")
    onboarding = await c.session.get(PodCase, link) if link else None
    if onboarding is None or onboarding.status != CaseStatus.COMPLETED:
        ref = onboarding.reference if onboarding else "the onboarding case"
        raise StepFailedError(
            f"Waiting for {ref}: {choice.new_vendor_name} is being onboarded (AP1.R4)."
        )
    task = await c.session.scalar(
        select(PodPostingTask).where(
            PodPostingTask.case_id == onboarding.id,
            PodPostingTask.kind == TaskKind.CREATE_SUPPLIER,
            PodPostingTask.status == TaskStatus.VERIFIED,
        )
    )
    vendor_id = task.external_txn_id if task else None
    if not vendor_id or vendor_id not in _active(await doc_of(c)):
        raise StepFailedError(
            f"{choice.new_vendor_name} is onboarded, but this case's snapshot doesn't hold it "
            "yet: move the case to a fresh ERPNext snapshot, then run again."
        )
    return vendor_id


async def draft_po(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    want = need(c, "1.1.1.a", Need)
    coding = need(c, "1.1.2.a", Coding)
    comparison = result(c, "1.3.1.c", Comparison)
    choice = need(c, "1.3.2.b", VendorChoice)
    vendor = await chosen_vendor(c)
    quote = next(
        (
            q
            for q in (comparison.quotes if comparison else [])
            if q.reference == choice.quote_reference
        ),
        None,
    )
    items = {i.code: i for i in doc.items or []}
    lines: list[PoLine] = []
    for ln in want.lines:
        if quote and ln.item_code in quote.rates:
            rate, source = quote.rates[ln.item_code], "quote"
        elif (contract := _contract_rate(doc, ln.item_code, vendor)) is not None:
            rate, source = contract, "contract"
        elif (catalogue := _catalogue_rate(doc, ln.item_code)) is not None:
            rate, source = catalogue, "catalogue"
        else:
            raise StepFailedError(f"No price for {ln.item_code} from {vendor}: record its quote.")
        lines.append(
            PoLine(item_code=ln.item_code, quantity=ln.quantity, rate=rate, rate_source=source,
                   amount=cents(rate * ln.quantity), needed_by=want.needed_by)
        )  # fmt: skip
    total = cents(sum((ln.amount for ln in lines), Decimal(0)))
    return {
        "1.6.1.a": DraftPo(vendor_id=vendor, lines=lines, total=total, currency=doc.currency),
        "1.6.1.b": PoCoding(
            lines=[
                PoLineCoding(
                    item_code=ln.item_code,
                    cost_centre_id=coding.cost_centre_id,
                    lab_id=coding.lab_id,
                    grant_id=coding.grant_id,
                    account_id=items[ln.item_code].expense_account_id
                    if ln.item_code in items
                    else None,
                )
                for ln in lines
            ],
            terms=choice.terms,
        ),
    }


async def below_po_limit(c: Ctx) -> str | None:
    draft = result(c, "1.6.1.a", DraftPo)
    limit = _policy(c).po_approval_limit
    if draft is not None and draft.total <= limit:
        return f"At or below the PO approval limit ({limit:,.2f}): no buyer approval needed"
    return None


def erp_po(c: Ctx, doc: SnapshotDocument, draft: DraftPo, coding: PoCoding) -> dict[str, object]:
    """The ERPNext Purchase Order the approved draft becomes (posted by a person's action)."""
    codes = {ln.item_code: ln for ln in coding.lines}
    first = min(ln.needed_by for ln in draft.lines)
    return {
        "supplier": draft.vendor_id,
        "company": doc.company_name,
        "transaction_date": utcnow().date().isoformat(),
        "schedule_date": first.isoformat(),
        "currency": draft.currency,
        "terms": coding.terms,
        "items": [
            {
                "item_code": ln.item_code,
                "qty": str(ln.quantity),
                "rate": str(ln.rate),
                "schedule_date": ln.needed_by.isoformat(),
                "cost_center": codes[ln.item_code].cost_centre_id,
                "lab": codes[ln.item_code].lab_id,
                "project": codes[ln.item_code].grant_id,
                "expense_account": codes[ln.item_code].account_id,
            }
            for ln in draft.lines
        ],
    }


async def send_po(c: Ctx, step: StepSpec) -> Results:
    """After the release: post the PO to ERPNext, draft its email to the vendor (a buyer
    sends it), and finish once the vendor's acknowledgement is logged."""
    if c.request is None:
        raise StepFailedError("Run this step from the case.")
    doc = await doc_of(c)
    draft = need(c, "1.6.1.a", DraftPo)
    coding = need(c, "1.6.1.b", PoCoding)
    task = await c.session.scalar(
        select(PodPostingTask).where(
            PodPostingTask.case_id == c.case.id,
            PodPostingTask.kind == TaskKind.CREATE_PURCHASE_ORDER,
            PodPostingTask.status != TaskStatus.CANCELLED,
        )
    )
    if task is None:
        task = await tasks.add_task(
            c.session, c.case,
            TaskCreate(kind=TaskKind.CREATE_PURCHASE_ORDER, reference=c.case.reference,
                       instructions={"doc": erp_po(c, doc, draft, coding)}),
            c.user.id,
        )  # fmt: skip
    if task.status == TaskStatus.PROPOSED:
        try:
            await tasks.post_now(c.session, c.access, task, c.case, c.request)
        except tasks.TaskRefusedError as exc:
            raise StepFailedError(f"Posting the PO to ERPNext failed: {exc.message}") from exc
    po_name = task.external_txn_id or ""
    vendor = next((v for v in doc.vendors or [] if v.id == draft.vendor_id), None)
    if vendor is None or not vendor.email:
        raise StepFailedError(
            f"PO {po_name} is in ERPNext, but {draft.vendor_id} has no verified email: add the "
            "contact in ERPNext, move the case to a fresh snapshot and run again."
        )
    lines = "\n".join(
        f"- {ln.item_code}: {ln.quantity.normalize()} x {money_text(ln.rate, draft.currency)}"
        f" = {money_text(ln.amount, draft.currency)}, by {ln.needed_by.isoformat()}"
        for ln in draft.lines
    )
    message = await draft_once(
        c, purpose="purchase_order", audience=Audience.VENDOR, to_email=vendor.email,
        to_name=vendor.name, subject=f"Purchase order {po_name}",
        body=(f"Dear {vendor.name},\n\nPlease find our purchase order {po_name}:\n\n{lines}\n\n"
              f"Total: {money_text(draft.total, draft.currency)}\nTerms: {coding.terms}\n\n"
              "Please confirm receipt of this order by replying to this email."),
    )  # fmt: skip
    if not is_sent(message):
        raise StepFailedError(
            f"PO {po_name} is in ERPNext and its email to {vendor.name} is drafted: a buyer "
            "reviews and sends it, then runs this step again."
        )
    ack = c.case.state.get("_po_acknowledgement")
    if not ack:
        raise StepFailedError(
            f"PO {po_name} sent to {vendor.name}: log their acknowledgement when it arrives."
        )
    return {
        "1.6.1.c": PoSent(
            erp_po=po_name, task_id=task.id, message_id=message.id,
            acknowledgement=Acknowledgement.model_validate(ack),
        )
    }  # fmt: skip
