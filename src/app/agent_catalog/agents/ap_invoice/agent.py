from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.ap_invoice import prompt
from src.app.agent_catalog.agents.ap_invoice.models import ApInvoiceRun
from src.app.agent_catalog.agents.ap_invoice.schemas import ApInvoiceInput, ApInvoicePolicy
from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
    Prefill,
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
from src.app.data_sources.records import Bill, PurchaseOrder, Record, RecordType, Vendor


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
        values: dict[str, Any] = {
            "supplier": bill.vendor_name,
            "invoice_number": bill.doc_number,
            "invoice_total": bill.total,
            "tax_total": bill.tax_total,
            "proposed_gl_account": bill.account,
        }
        related: dict[str, Record] = {}
        if bill.po_number:
            po = await data.find(PurchaseOrder, RecordType.PURCHASE_ORDER, bill.po_number)
            if po is not None:
                related["purchase_order"] = po
                values["po_authorized_amount"] = po.total
                if po.received_amount is not None:
                    values["received_amount"] = po.received_amount
        # Only what the source knows: the preparer completes the rest
        return Prefill({k: v for k, v in values.items() if v is not None}, related)

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
