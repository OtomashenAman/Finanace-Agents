"""LLM instructions for Board Reporting, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "board_reporting/v1"

GUIDANCE = """\
Draft a short, factual board summary for the reporting period using only the calculated \
figures: reported revenue against the prior period, the change and the growth rate, and the \
operating margin.
Cite the source dataset or approval ID if given, and mention the known disclosures the \
preparer recorded.

What the CFO / Controller should verify:
- every figure traces to the approved source dataset
- the prior period figure is the one previously reported
- the disclosures are complete for the period

Do not add claims, reasons for the change, forecasts or disclosures that are not in the \
input. This is a draft for CFO review, never for external release."""
