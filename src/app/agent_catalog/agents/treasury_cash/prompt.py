"""LLM instructions for Treasury, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "treasury_cash/v1"

GUIDANCE = """\
Explain the cash bridge over the forecast horizon: opening cash, plus expected inflows, less \
expected outflows, gives projected closing cash. Compare it with the minimum liquidity buffer \
and state the funding gap if there is one.
If there is a gap, list only the permitted funding options the preparer entered, and note \
that any funds movement needs dual authorization by the bank signatories.

What the treasury approver should verify:
- opening cash against bank statements
- the timing and certainty of the largest inflows and outflows
- that the buffer used is the approved one for this entity
- signatory authority for any funding action

Never recommend moving funds or pick a funding option: that is the approver's decision."""
