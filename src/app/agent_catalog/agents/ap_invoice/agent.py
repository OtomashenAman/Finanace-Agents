from decimal import Decimal
from typing import cast

from pydantic import BaseModel
from sqlalchemy import func, select

from src.app.agent_catalog.agents.ap_invoice.models import ApInvoiceRun
from src.app.agent_catalog.agents.ap_invoice.schemas import ApInvoiceInput
from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
)
from src.app.agent_catalog.runs.models import AgentRun, FlagSeverity, RunStatus

ZERO = Decimal("0.00")


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


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
    policy_version = "ap_invoice/v1"
    controls = (
        "Duplicate supplier/invoice",
        "PO/receipt mismatch",
        "Missing GL or evidence",
        "Amount validity",
    )
    narrative_guidance = (
        "Explain the three-way match between invoice, purchase order and receipt, any "
        "duplicate risk and missing coding or evidence. Point out what the AP approver "
        "should verify in the source documents."
    )

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        invoice = cast(ApInvoiceInput, data)
        findings: list[Finding] = []

        duplicate_of = await ctx.session.scalar(
            select(AgentRun.run_number)
            .join(ApInvoiceRun, ApInvoiceRun.run_id == AgentRun.id)
            .where(
                AgentRun.id != ctx.run.id,
                AgentRun.status.not_in([RunStatus.DRAFT, RunStatus.VALIDATION_FAILED]),
                func.lower(ApInvoiceRun.supplier) == invoice.supplier.lower(),
                func.lower(ApInvoiceRun.invoice_number) == invoice.invoice_number.lower(),
            )
            .order_by(AgentRun.run_number)
            .limit(1)
        )
        if duplicate_of is not None:
            findings.append(
                Finding(
                    "DUPLICATE_INVOICE",
                    FlagSeverity.HIGH,
                    f"Same supplier and invoice number already analyzed in RUN-{duplicate_of:05d}",
                    "invoice_number",
                )
            )
        else:
            findings.append(
                Finding(
                    "DUPLICATE_CHECK_CLEAR",
                    FlagSeverity.PASS,
                    "No earlier run with this supplier and invoice number",
                    "invoice_number",
                )
            )

        invoice_vs_po = invoice.invoice_total - invoice.po_authorized_amount
        invoice_vs_receipt = invoice.invoice_total - invoice.received_amount
        if invoice_vs_po == ZERO:
            findings.append(
                Finding(
                    "PO_MATCH",
                    FlagSeverity.PASS,
                    "Invoice total matches the PO authorized amount",
                    "po_authorized_amount",
                )
            )
        else:
            findings.append(
                Finding(
                    "PO_MISMATCH",
                    FlagSeverity.HIGH,
                    f"Invoice total differs from the PO authorized amount by "
                    f"{_money(invoice_vs_po)}",
                    "po_authorized_amount",
                )
            )
        if invoice_vs_receipt == ZERO:
            findings.append(
                Finding(
                    "RECEIPT_MATCH",
                    FlagSeverity.PASS,
                    "Invoice total matches the received amount",
                    "received_amount",
                )
            )
        else:
            findings.append(
                Finding(
                    "RECEIPT_MISMATCH",
                    FlagSeverity.HIGH,
                    f"Invoice total differs from the received amount by "
                    f"{_money(invoice_vs_receipt)}",
                    "received_amount",
                )
            )

        if invoice.tax_total is not None and invoice.tax_total > invoice.invoice_total:
            findings.append(
                Finding(
                    "TAX_EXCEEDS_TOTAL",
                    FlagSeverity.HIGH,
                    "Tax total is greater than the invoice total",
                    "tax_total",
                )
            )
        if not invoice.proposed_gl_account:
            findings.append(
                Finding(
                    "MISSING_GL",
                    FlagSeverity.WARNING,
                    "No proposed GL account: coding is required before approval",
                    "proposed_gl_account",
                )
            )
        if ctx.document_count == 0:
            findings.append(
                Finding(
                    "MISSING_EVIDENCE",
                    FlagSeverity.WARNING,
                    "No supporting documents attached (invoice, PO or receipt)",
                )
            )

        exceptions = any(f.severity == FlagSeverity.HIGH for f in findings)
        if duplicate_of is not None:
            headline = "Duplicate invoice suspected"
        elif exceptions:
            headline = "Invoice discrepancy"
        elif any(f.severity == FlagSeverity.WARNING for f in findings):
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
