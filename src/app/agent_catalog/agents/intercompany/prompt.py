"""LLM instructions for Intercompany, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "intercompany/v1"

GUIDANCE = """\
Explain the intercompany match between the sending entity's AR and the receiving entity's AP: \
the translation rate applied, the translated AP, the difference against the matching \
tolerance, and the amount available to net.
If the balances don't match, describe the break as something to resolve before settlement, \
using the transfer-pricing notes if given.

What the treasury and tax reviewer should verify:
- both balances against each entity's ledger for the same date
- the source and date of the translation rate
- transfer-pricing documentation for the underlying charges
- authorization for any netting or settlement

Never state that a settlement, netting or transfer was made or should be executed."""
