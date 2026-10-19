from typing import Any

from src.app.agent_catalog.runs.narrative import check_output
from src.app.agent_catalog.runs.schemas import NarrativeOutput

PAYLOAD: dict[str, Any] = {
    "input": {"invoice_total": "12500.00", "received_amount": "1000.00"},
    "calculations": [
        {"key": "invoice_vs_receipt", "label": "Invoice - received", "value": "11500.00"}
    ],
    "findings": [{"message": "Invoice total differs from the received amount by 11,500.00"}],
    "documents": [{"id": "D1", "filename": "inv.pdf", "text": "Invoice INV-2048 dated 2026-10-01"}],
}


def output(**overrides: Any) -> NarrativeOutput:
    base: dict[str, Any] = {
        "summary": "The invoice total of 12,500.00 exceeds the received amount of 1,000.00.",
        "key_points": [],
        "cited_fields": ["invoice_total"],
        "cited_documents": ["D1"],
        "missing_evidence": [],
        "ambiguities": [],
    }
    return NarrativeOutput(**{**base, **overrides})


def test_grounded_output_has_no_warnings() -> None:
    assert check_output(output(), PAYLOAD) == []


def test_figures_match_regardless_of_formatting_and_sign() -> None:
    text = "Difference -11500 vs 12500; received 1000.00 per INV-2048 in 2026."
    assert check_output(output(summary=text), PAYLOAD) == []


def test_invented_figure_is_flagged() -> None:
    warnings = check_output(output(key_points=["Tax of 1,250.00 is included"]), PAYLOAD)
    assert warnings == ["Figure not found in the source data: 1,250.00"]


def test_small_counts_and_years_are_not_policed() -> None:
    assert check_output(output(summary="2 documents reviewed in 2027."), PAYLOAD) == []


def test_unknown_citations_are_flagged() -> None:
    warnings = check_output(output(cited_fields=["bank_account"], cited_documents=["D9"]), PAYLOAD)
    assert warnings == [
        "Cited a document that wasn't provided: D9",
        "Cited a field that doesn't exist: bank_account",
    ]
