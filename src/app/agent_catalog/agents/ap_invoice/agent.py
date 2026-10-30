from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.ap_invoice import prompt
from src.app.agent_catalog.agents.ap_invoice.models import ApInvoiceRun
from src.app.agent_catalog.agents.ap_invoice.schemas import ApInvoiceInput, ApInvoicePolicy
from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    Autofill,
    BaseAgent,
    Calculation,
    Evidence,
    Finding,
    Prefill,
    as_of,
    record_snapshot,
)
from src.app.agent_catalog.agents.checks import (
    ZERO,
    duplicate_check,
    evidence_check,
    has_severity,
    missing,
    money,
    over_limit,
    tolerance_check,
)
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource
from src.app.data_sources.records import (
    Bill,
    BillPayment,
    DocLine,
    PurchaseOrder,
    Record,
    RecordType,
    Vendor,
    VendorCredit,
)


class ApInvoiceAgent(BaseAgent):
    key = "ap_invoice"
    code = "01"
    name = "AP Invoice Intake, Coding & Approval"
    short_name = "AP Invoice"
    description = (
        "Extract invoice details, compare PO and receipt, assign GL and flag "
        "duplicate/tax/policy exceptions."
    )
    primary_user = "AP Analyst"
    reviewer = "AP Approver"

    input_schema = ApInvoiceInput
    run_model = ApInvoiceRun
    reference_field = "invoice_number"
    bill_fields = ("supplier", "invoice_number", "invoice_total")
    bill_account_field = "proposed_gl_account"
    policy_version = "ap_invoice/v1"
    controls = (
        "Duplicate supplier/invoice",
        "PO/receipt mismatch",
        "Missing GL or evidence",
        "Amount validity",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    source_record_type = RecordType.BILL
    policy_schema = ApInvoicePolicy
    approval_amount_label = "Invoice total"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return cast(ApInvoiceInput, data).invoice_total

    @classmethod
    async def prefill(
        cls,
        record: Record,
        source: DataSource,
        data: FinanceData,
        policy: PolicySettings | None = None,
    ) -> Prefill:
        bill = cast(Bill, record)
        tolerance = cast(ApInvoicePolicy, policy).po_tolerance if policy else ZERO
        values: dict[str, Any] = {
            "supplier": bill.vendor_name,
            "invoice_number": bill.doc_number,
            "invoice_total": bill.total,
            "tax_total": bill.tax_total,
            "proposed_gl_account": bill.account,
        }
        related: dict[str, Record] = {}
        match, _ = await match_purchase_order(
            data, bill.vendor_name, bill.po_number, bill.total, tolerance, bill.doc_number
        )
        if match is not None:
            related["purchase_order"] = match.po
            values["po_authorized_amount"] = match.available
            values["received_amount"] = match.received_available
        if bill.account is None:
            values["proposed_gl_account"], _ = await usual_account(
                data, bill.vendor_name, exclude=bill.doc_number
            )
        # Only what the source knows: the preparer completes the rest
        return Prefill({k: v for k, v in values.items() if v is not None}, related)

    @classmethod
    async def autofill(
        cls, values: dict[str, Any], data: FinanceData, policy: PolicySettings | None = None
    ) -> Autofill:
        """Find the invoice's PO (and what was received against it) and code the GL account
        from the preparer's data, for whatever the preparer left empty."""
        supplier = values.get("supplier")
        if not supplier:
            return Autofill()
        tolerance = cast(ApInvoicePolicy, policy).po_tolerance if policy else ZERO
        number = values.get("invoice_number")
        result = Autofill()

        bill = None
        if number:
            bills = await data.records(Bill, RecordType.BILL, counterparty=supplier)
            bill = next((b for b in bills if b.doc_number.lower() == number.lower()), None)
        bill_source = await data.source_for(RecordType.BILL) if bill else None
        if bill is not None:  # the invoice is in the books: its total and tax too
            entered_total = values.get("invoice_total")
            if entered_total is not None and Decimal(entered_total) != bill.total:
                result.notes.append(
                    Finding(
                        "TOTAL_DIFFERS_FROM_BOOKS",
                        FlagSeverity.HIGH,
                        f"Bill {bill.doc_number} of {bill.vendor_name} is {money(bill.total)} "
                        f"in your data, not {money(Decimal(entered_total))}",
                        "invoice_total",
                    )
                )
            values = {**values}
            for name, value in (("invoice_total", bill.total), ("tax_total", bill.tax_total)):
                if values.get(name) is None and value is not None:
                    values[name] = result.values[name] = value
                    result.sources[name] = f"bill {bill.doc_number}"
            if result.values:
                result.notes.append(
                    Finding(
                        "FILLED_FROM_DATA",
                        FlagSeverity.INFO,
                        f"Filled {' and '.join(k.replace('_', ' ') for k in result.values)} "
                        f"from bill {bill.doc_number} in your data{as_of(bill_source)}",
                        next(iter(result.values)),
                    )
                )
        total = values.get("invoice_total")

        match = None
        if values.get("po_authorized_amount") is None or values.get("received_amount") is None:
            match, why_not = await match_purchase_order(
                data, supplier, bill.po_number if bill else None, total, tolerance, number
            )
            if match is not None:
                result.values["po_authorized_amount"] = match.available
                result.values["received_amount"] = match.received_available
                for name in ("po_authorized_amount", "received_amount"):
                    result.sources[name] = f"purchase order {match.po.po_number}"
                po_source = await data.source_for(RecordType.PURCHASE_ORDER)
                result.notes.append(
                    Finding(
                        "PO_FOUND",
                        FlagSeverity.INFO,
                        f"Found {match.describe()} in your data: {match.how}{as_of(po_source)}",
                        "po_authorized_amount",
                    )
                )
                if match.po.received_amount is None and values.get("received_amount") is None:
                    result.notes.append(
                        Finding(
                            "RECEIPT_NOT_IN_DATA",
                            FlagSeverity.WARNING,
                            f"Your data has no received amount for {match.po.po_number}: "
                            "enter what was received",
                            "received_amount",
                        )
                    )
            elif why_not:
                result.notes.append(
                    Finding("PO_NOT_FOUND", FlagSeverity.WARNING, why_not, "po_authorized_amount")
                )

        # Freeze the bill (or, without one, the PO) for the reviewer
        related: dict[str, Record] = {"purchase_order": match.po} if match else {}
        if bill is not None and bill_source is not None:
            result.evidence = Evidence(
                bill_source, "bill", bill.doc_number, record_snapshot("bill", bill, related)
            )
        elif match is not None:
            po_source = await data.source_for(RecordType.PURCHASE_ORDER)
            if po_source is not None:
                result.evidence = Evidence(
                    po_source,
                    "purchase_order",
                    match.po.po_number,
                    record_snapshot("purchase_order", match.po, {}),
                )

        if not values.get("proposed_gl_account"):
            # The bill's own coding, else the PO items' expense accounts, else the supplier's
            # usual account
            account = bill.account if bill else None
            how: str | None = "from the bill in your data"
            origin = f"bill {bill.doc_number}" if bill else ""
            po_accounts = Counter(
                line.account for line in (match.po.lines if match else []) if line.account
            )
            if account is None and match is not None and po_accounts:
                account = po_accounts.most_common(1)[0][0]
                how = f"from the items on {match.po.po_number}"
                origin = f"purchase order {match.po.po_number}"
            if account is None:
                account, how = await usual_account(data, supplier, exclude=number)
                origin = f"{supplier}'s bills"
            if account is not None:
                result.values["proposed_gl_account"] = account
                result.sources["proposed_gl_account"] = origin
                result.notes.append(
                    Finding(
                        "GL_CODED",
                        FlagSeverity.INFO,
                        f"Coded to {account} {how}",
                        "proposed_gl_account",
                    )
                )
        return result

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        invoice = cast(ApInvoiceInput, data)
        policy = cast(ApInvoicePolicy, ctx.policy) if ctx.policy else ApInvoicePolicy()

        duplicate, duplicate_of = await duplicate_check(
            ctx,
            ApInvoiceRun,
            what="supplier and invoice number",
            duplicate_code="DUPLICATE_INVOICE",
            clear_code="DUPLICATE_CHECK_CLEAR",
            field="invoice_number",
            supplier=invoice.supplier,
            invoice_number=invoice.invoice_number,
        )
        findings: list[Finding] = [duplicate]
        findings.extend(await cls._vendor_master_check(invoice.supplier, ctx))
        findings.extend(await cls._payments_and_credits_check(invoice, ctx))

        invoice_vs_po = invoice.invoice_total - invoice.po_authorized_amount
        invoice_vs_receipt = invoice.invoice_total - invoice.received_amount
        findings.append(
            tolerance_check(
                invoice_vs_po,
                policy.po_tolerance,
                subject="Invoice total",
                other="the PO authorized amount",
                tolerance_name="PO",
                match_code="PO_MATCH",
                mismatch_code="PO_MISMATCH",
                field="po_authorized_amount",
            )
        )
        findings.append(
            tolerance_check(
                invoice_vs_receipt,
                policy.receipt_tolerance,
                subject="Invoice total",
                other="the received amount",
                tolerance_name="receipt",
                match_code="RECEIPT_MATCH",
                mismatch_code="RECEIPT_MISMATCH",
                field="received_amount",
            )
        )

        findings.extend(await cls._line_checks(invoice, policy, ctx))

        optional_checks = [
            over_limit(
                invoice.invoice_total,
                policy.high_value_amount,
                code="HIGH_VALUE_INVOICE",
                message=(
                    f"Invoice total exceeds the {money(policy.high_value_amount or ZERO)} "
                    "high-value limit: review with extra care"
                ),
                field="invoice_total",
            ),
            over_limit(
                invoice.tax_total,
                invoice.invoice_total,
                code="TAX_EXCEEDS_TOTAL",
                message="Tax total is greater than the invoice total",
                field="tax_total",
                severity=FlagSeverity.HIGH,
            ),
            missing(
                invoice.proposed_gl_account,
                code="MISSING_GL",
                message="No proposed GL account: coding is required before approval",
                field="proposed_gl_account",
            ),
            evidence_check(ctx, "invoice, PO or receipt"),
        ]
        findings.extend(f for f in optional_checks if f is not None)

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if duplicate_of is not None:
            headline = "Duplicate invoice suspected"
        elif exceptions:
            headline = "Invoice discrepancy"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Invoice needs completion"
        else:
            headline = "Invoice matches PO and receipt"

        calculations = [
            Calculation("invoice_total", "Invoice total", invoice.invoice_total),
            Calculation(
                "po_authorized_amount", "PO authorized amount", invoice.po_authorized_amount
            ),
            Calculation("received_amount", "Received amount", invoice.received_amount),
            Calculation("invoice_vs_po", "Invoice - PO", invoice_vs_po),
            Calculation("invoice_vs_receipt", "Invoice - received", invoice_vs_receipt),
        ]
        if invoice.tax_total is not None:
            calculations.insert(3, Calculation("tax_total", "Tax total", invoice.tax_total))

        return Analysis(
            headline=headline,
            proposed_decision=(
                "Resolve exceptions before approval"
                if exceptions
                else "AP reviewer approval required"
            ),
            calculations=calculations,
            findings=findings,
            computed={"invoice_vs_po": invoice_vs_po, "invoice_vs_receipt": invoice_vs_receipt},
        )

    @staticmethod
    async def _line_checks(
        invoice: ApInvoiceInput, policy: ApInvoicePolicy, ctx: AnalysisContext
    ) -> list[Finding]:
        """Three-way match by line when the invoice's bill and its PO both have lines."""
        bills = await ctx.data.records(Bill, RecordType.BILL, counterparty=invoice.supplier)
        number = invoice.invoice_number.lower()
        bill = next((b for b in bills if b.doc_number.lower() == number), None)
        if bill is None or not bill.lines:
            return []
        match, _ = await match_purchase_order(
            ctx.data,
            invoice.supplier,
            bill.po_number,
            invoice.invoice_total,
            policy.po_tolerance,
            invoice.invoice_number,
        )
        if match is None:
            return []
        if not match.po.lines:
            return [
                Finding(
                    "PO_HAS_NO_LINES",
                    FlagSeverity.INFO,
                    f"{match.po.po_number} has no item lines in your data: matched on totals only",
                    "po_authorized_amount",
                )
            ]
        return match_lines(bill.lines, match.po.lines, match.po.po_number, policy.po_tolerance)

    @staticmethod
    async def _payments_and_credits_check(
        invoice: ApInvoiceInput, ctx: AnalysisContext
    ) -> list[Finding]:
        """Against the supplier's payments and credits in the books: an invoice already paid
        is a duplicate-payment risk; open supplier credits should be used first."""
        findings: list[Finding] = []
        payments = await ctx.data.records(
            BillPayment, RecordType.BILL_PAYMENT, counterparty=invoice.supplier
        )
        paid_by = [p for p in payments if p.pays(invoice.invoice_number)]
        if paid_by:
            numbers = ", ".join(
                f"{p.payment_number} ({p.payment_date or 'no date'})" for p in paid_by
            )
            findings.append(
                Finding(
                    "ALREADY_PAID",
                    FlagSeverity.HIGH,
                    f"Invoice {invoice.invoice_number} was already paid by {numbers}: "
                    "paying it again would be a duplicate payment",
                    "invoice_number",
                )
            )
        credits = await ctx.data.records(
            VendorCredit, RecordType.VENDOR_CREDIT, counterparty=invoice.supplier
        )
        open_credits = [c for c in credits if c.open_amount > ZERO]
        if open_credits:
            total = sum((c.open_amount for c in open_credits), ZERO)
            numbers = ", ".join(c.doc_number for c in open_credits[:5])
            findings.append(
                Finding(
                    "SUPPLIER_CREDIT_AVAILABLE",
                    FlagSeverity.WARNING,
                    f"{invoice.supplier} has {money(total)} of unused credits ({numbers}): "
                    "apply them before paying",
                    "invoice_total",
                )
            )
        return findings

    @staticmethod
    async def _vendor_master_check(supplier: str, ctx: AnalysisContext) -> list[Finding]:
        """Against the preparer's vendor master (QuickBooks or an upload), when they have one."""
        if not await ctx.data.has(RecordType.VENDOR):
            return []
        vendor = await ctx.data.find(Vendor, RecordType.VENDOR, supplier)
        if vendor is None:
            return [
                Finding(
                    "VENDOR_NOT_IN_MASTER",
                    FlagSeverity.WARNING,
                    f"'{supplier}' is not in your vendor master: confirm the supplier is approved",
                    "supplier",
                )
            ]
        if not vendor.active:
            return [
                Finding(
                    "VENDOR_INACTIVE",
                    FlagSeverity.HIGH,
                    f"'{vendor.name}' is inactive in your vendor master",
                    "supplier",
                )
            ]
        return [
            Finding(
                "VENDOR_IN_MASTER",
                FlagSeverity.PASS,
                f"'{vendor.name}' is an active vendor in your vendor master",
                "supplier",
            )
        ]


# PO statuses (QuickBooks or uploads) that mean nothing more may be billed against it
CLOSED_PO_STATUSES = frozenset(
    {
        "closed",
        "cancelled",
        "canceled",
        "void",
        "voided",
        "complete",
        "completed",
        "billed",
        "fully billed",
    }
)


@dataclass(frozen=True)
class PoMatch:
    """A PO for an invoice, net of what the supplier's other bills already billed against it."""

    po: PurchaseOrder
    how: str
    billed: Decimal
    billed_by: tuple[str, ...]

    @property
    def available(self) -> Decimal:
        """Authorized and not yet billed: what this invoice may still bill."""
        return max(self.po.total - self.billed, ZERO)

    @property
    def received_available(self) -> Decimal | None:
        """Received and not yet billed; None when the data has no received amount."""
        if self.po.received_amount is None:
            return None
        return max(self.po.received_amount - self.billed, ZERO)

    def describe(self) -> str:
        text = f"{self.po.po_number} ({money(self.po.total)}"
        if self.billed:
            text += f", {money(self.billed)} already billed by {', '.join(self.billed_by)}"
        return f"{text}, {money(self.available)} left to bill)"


async def _billed_against(
    data: FinanceData, po: PurchaseOrder, exclude: str | None
) -> tuple[Decimal, tuple[str, ...]]:
    """What the supplier's other bills linked to `po` add up to, and their numbers."""
    bills = await data.records(Bill, RecordType.BILL, counterparty=po.vendor_name)
    others = [
        b
        for b in bills
        if b.po_number
        and b.po_number.lower() == po.po_number.lower()
        and (exclude is None or b.doc_number.lower() != exclude.lower())
    ]
    return sum((b.total for b in others), ZERO), tuple(b.doc_number for b in others)


async def match_purchase_order(
    data: FinanceData,
    supplier: str,
    po_number: str | None,
    invoice_total: Decimal | None,
    tolerance: Decimal,
    invoice_number: str | None = None,
) -> tuple[PoMatch | None, str | None]:
    """The invoice's PO in the preparer's data, or why none was taken.

    By the PO number the bill is linked to; otherwise, among the supplier's POs that are open
    and not fully billed, the one whose amount left to bill is within the PO tolerance of the
    invoice total, or the only one. Never guesses between several.
    """
    if po_number:
        po = await data.find(PurchaseOrder, RecordType.PURCHASE_ORDER, po_number)
        if po is not None:
            billed, by = await _billed_against(data, po, invoice_number)
            return PoMatch(po, "the PO the bill is linked to", billed, by), None
    orders = await data.records(PurchaseOrder, RecordType.PURCHASE_ORDER, counterparty=supplier)
    candidates = []
    for po in orders:
        if (po.status or "").strip().lower() in CLOSED_PO_STATUSES:
            continue
        billed, by = await _billed_against(data, po, invoice_number)
        match = PoMatch(po, "", billed, by)
        if match.available > ZERO:
            candidates.append(match)
    if not candidates:
        if not await data.has(RecordType.PURCHASE_ORDER):
            return None, None  # no PO data at all: nothing to say
        return None, (
            f"No open PO with an amount left to bill for '{supplier}' in your data: "
            "enter the PO authorized amount"
        )
    if invoice_total is not None:
        same = [m for m in candidates if abs(m.available - invoice_total) <= tolerance]
        if len(same) == 1:
            return replace(same[0], how=f"the open PO of '{supplier}' for this amount"), None
        if len(same) > 1:
            numbers = ", ".join(m.po.po_number for m in same)
            return None, f"Several open POs of '{supplier}' match the invoice total ({numbers})"
    if len(candidates) == 1:
        return replace(candidates[0], how=f"the only open PO of '{supplier}'"), None
    numbers = ", ".join(m.po.po_number for m in candidates)
    return None, f"'{supplier}' has several open POs ({numbers}): enter the one this invoice bills"


def _by_item(lines: list[DocLine]) -> dict[str, list[DocLine]]:
    grouped: dict[str, list[DocLine]] = {}
    for line in lines:
        grouped.setdefault(line.item.strip().lower(), []).append(line)
    return grouped


def _total_quantity(lines: list[DocLine]) -> Decimal | None:
    if any(line.quantity is None for line in lines):
        return None
    return sum((line.quantity or ZERO for line in lines), ZERO)


def match_lines(
    bill_lines: list[DocLine], po_lines: list[DocLine], po_number: str, tolerance: Decimal
) -> list[Finding]:
    """Line-level match of an invoice against its PO: each item must be on the PO, within the
    quantity ordered and at the PO's unit price (an amount difference above the PO tolerance
    is an exception)."""
    ordered = _by_item(po_lines)
    findings: list[Finding] = []
    for key, billed in _by_item(bill_lines).items():
        name = billed[0].item
        amount = sum((line.amount for line in billed), ZERO)
        on_po = ordered.get(key)
        if not on_po:
            findings.append(
                Finding(
                    "LINE_NOT_ON_PO",
                    FlagSeverity.HIGH,
                    f"'{name}' ({money(amount)}) is billed but not on {po_number}",
                    "po_authorized_amount",
                )
            )
            continue
        billed_qty, ordered_qty = _total_quantity(billed), _total_quantity(on_po)
        if billed_qty is not None and ordered_qty is not None and billed_qty > ordered_qty:
            findings.append(
                Finding(
                    "LINE_QUANTITY_OVER",
                    FlagSeverity.HIGH,
                    f"'{name}': {billed_qty.normalize():f} billed vs {ordered_qty.normalize():f} "
                    f"ordered on {po_number}",
                    "received_amount",
                )
            )
        po_price, bill_price = on_po[0].unit_price, billed[0].unit_price
        if po_price is not None and bill_price is not None and billed_qty is not None:
            excess = (bill_price - po_price) * billed_qty
            if abs(excess) > tolerance:
                findings.append(
                    Finding(
                        "LINE_PRICE_DIFFERS",
                        FlagSeverity.HIGH,
                        f"'{name}': billed at {money(bill_price)} vs {money(po_price)} on "
                        f"{po_number} ({money(excess)} on {billed_qty.normalize():f} units)",
                        "invoice_total",
                    )
                )
        elif amount - sum((line.amount for line in on_po), ZERO) > tolerance:
            findings.append(
                Finding(
                    "LINE_AMOUNT_OVER",
                    FlagSeverity.HIGH,
                    f"'{name}': {money(amount)} billed vs "
                    f"{money(sum((line.amount for line in on_po), ZERO))} on {po_number}",
                    "invoice_total",
                )
            )
    if not findings:
        findings.append(
            Finding(
                "LINES_MATCH",
                FlagSeverity.PASS,
                f"All {len(bill_lines)} invoice line{'' if len(bill_lines) == 1 else 's'} match "
                f"{po_number} (item, quantity and price)",
                "po_authorized_amount",
            )
        )
    not_billed = [
        lines[0].item for key, lines in ordered.items() if key not in _by_item(bill_lines)
    ]
    if not_billed:
        findings.append(
            Finding(
                "PO_LINES_NOT_BILLED",
                FlagSeverity.INFO,
                f"Not on this invoice yet: {', '.join(not_billed[:5])}"
                + (f" and {len(not_billed) - 5} more" if len(not_billed) > 5 else ""),
                "po_authorized_amount",
            )
        )
    return findings


async def usual_account(
    data: FinanceData, supplier: str, exclude: str | None = None
) -> tuple[str | None, str | None]:
    """The GL account most of the supplier's other bills are coded to, and how it was chosen."""
    bills = await data.records(Bill, RecordType.BILL, counterparty=supplier)
    accounts = Counter(
        b.account
        for b in bills
        if b.account and (exclude is None or b.doc_number.lower() != exclude.lower())
    )
    if not accounts:
        return None, None
    account, count = accounts.most_common(1)[0]
    return account, f"(used on {count} of the {accounts.total()} coded bills of '{supplier}')"
