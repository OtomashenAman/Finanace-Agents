from typing import Any

from src.app.agent_catalog.runs.narrative import check_output, output_schema
from src.app.agent_catalog.runs.schemas import NarrativeOutput, NarrativeResult

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


# --- drafts (agents with draft_message) ----------------------------------------------------


def test_output_schema_asks_for_a_draft_only_when_the_agent_has_one() -> None:
    assert "draft_message" not in output_schema(PAYLOAD).model_fields
    with_draft = output_schema(PAYLOAD, "Payment reminder email to the customer")
    field = with_draft.model_fields["draft_message"]
    assert field.is_required()
    assert field.description == (
        "Payment reminder email to the customer: a draft for human review, never sent automatically"
    )


def test_invented_figure_in_the_draft_is_flagged() -> None:
    schema = output_schema(PAYLOAD, "Reminder")
    grounded = schema(
        **output().model_dump(), draft_message="Your invoice of 12,500.00 is still open."
    )
    assert check_output(grounded, PAYLOAD) == []
    invented = schema(**output().model_dump(), draft_message="Please pay 13,000.00 by Friday.")
    assert check_output(invented, PAYLOAD) == ["Figure not found in the source data: 13,000.00"]


def test_a_narrative_without_draft_dumps_as_before() -> None:
    """The result hash covers the narrative: drafts must not change it for other agents."""
    stored = output().model_dump()
    assert NarrativeResult(**stored).model_dump(exclude_none=True) == stored
