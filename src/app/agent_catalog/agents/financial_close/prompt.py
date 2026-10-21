"""LLM instructions for Financial Close, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "financial_close/v1"

GUIDANCE = """\
Explain the reconciliation of the GL account for the close period: GL balance against \
subledger balance, how much the known reconciling items explain, and the unexplained \
difference compared with the materiality threshold.
If the preparer gave an adjustment rationale, summarise it as a draft explanation for review.

What the reviewing controller should verify:
- both balances against the GL detail and the subledger report for the same period
- each known reconciling item (timing, in-transit) and that it clears next period
- support for any proposed adjustment

Never state that a journal was posted or should be posted, and do not draft journal lines."""
