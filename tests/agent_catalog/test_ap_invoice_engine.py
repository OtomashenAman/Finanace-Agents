import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ap_invoice import ApInvoiceAgent
from src.app.agent_catalog.agents.ap_invoice.schemas import ApInvoiceInput
from src.app.agent_catalog.agents.base import Analysis, AnalysisContext
from src.app.agent_catalog.runs.models import AgentRun, RunPriority
from src.app.data_sources.access import FinanceData

# Values from the requirement deck's AP Invoice example
PDF_EXAMPLE = {
    "supplier": "Acme Cloud Services",
    "invoice_number": "INV-2048",
    "invoice_total": "12500.00",
    "po_authorized_amount": "12500.00",
    "received_amount": "1000",
}


async def analyze(db: AsyncSession, documents: int = 0, **overrides: object) -> Analysis:
    data = ApInvoiceInput.model_validate({**PDF_EXAMPLE, **overrides})
    run = AgentRun(id=uuid.uuid4(), run_number=1)
    no_sources = FinanceData(db, uuid.uuid4(), None)  # a preparer without data sources
    return await ApInvoiceAgent.analyze(
        data, AnalysisContext(session=db, run=run, document_count=documents, data=no_sources)
    )


def codes(analysis: Analysis) -> dict[str, str]:
    return {f.code: f.severity.value for f in analysis.findings}


async def test_pdf_example_flags_receipt_mismatch(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Invoice discrepancy"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Resolve exceptions before approval"
    assert codes(analysis) == {
        "DUPLICATE_CHECK_CLEAR": "pass",
        "PO_MATCH": "pass",
        "RECEIPT_MISMATCH": "high",
        "MISSING_GL": "warning",
        "MISSING_EVIDENCE": "warning",
    }
    mismatch = next(f for f in analysis.findings if f.code == "RECEIPT_MISMATCH")
    assert mismatch.message == "Invoice total differs from the received amount by 11,500.00"
    assert analysis.computed == {
        "invoice_vs_po": Decimal("0.00"),
        "invoice_vs_receipt": Decimal("11500.00"),
    }


async def test_clean_invoice_needs_only_reviewer_approval(db: AsyncSession) -> None:
    analysis = await analyze(
        db, documents=2, received_amount="12500.00", proposed_gl_account="6100-Software"
    )

    assert analysis.headline == "Invoice matches PO and receipt"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "AP reviewer approval required"
    assert set(codes(analysis).values()) == {"pass"}


async def test_over_po_invoice_and_tax_above_total(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        invoice_total="13000.00",
        received_amount="13000.00",
        tax_total="14000.00",
        proposed_gl_account="6100",
    )

    found = codes(analysis)
    assert found["PO_MISMATCH"] == "high"
    assert found["TAX_EXCEEDS_TOTAL"] == "high"
    assert analysis.computed["invoice_vs_po"] == Decimal("500.00")
    labels = [c.label for c in analysis.calculations]
    assert labels == [
        "Invoice total",
        "PO authorized amount",
        "Received amount",
        "Tax total",
        "Invoice - PO",
        "Invoice - received",
    ]


async def test_missing_gl_alone_is_a_warning_not_an_exception(db: AsyncSession) -> None:
    analysis = await analyze(db, documents=1, received_amount="12500.00")

    assert analysis.headline == "Invoice needs completion"
    assert analysis.priority == RunPriority.NORMAL
