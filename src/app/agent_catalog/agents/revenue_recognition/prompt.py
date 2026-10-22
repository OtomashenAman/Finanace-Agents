"""LLM instructions for Revenue Recognition, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "revenue_recognition/v1"

GUIDANCE = """\
Draft a short accounting memo on the contract facts under ASC 606 / IFRS 15: the customer, \
contract total, service term, the performance obligations listed and any variable \
consideration or modifications the preparer described.
Present the straight-line amount per month only as a preliminary illustration from the \
engine's figures. If more than one performance obligation is listed, say the transaction \
price must be allocated by standalone selling price before any schedule is final, and do \
not allocate it yourself.
Quote contract clauses only from the text the preparer entered; if none were entered, say so.

What the revenue controller should verify:
- whether each listed obligation is distinct, and if it is satisfied over time or at a point
- the transaction price, including any variable consideration and its constraint
- whether a contract change is a separate contract or a modification of this one
- the signed contract or order form behind the figures

Never state that revenue was recognized or a journal posted, and never conclude on the \
accounting treatment: that is the revenue controller's decision."""
