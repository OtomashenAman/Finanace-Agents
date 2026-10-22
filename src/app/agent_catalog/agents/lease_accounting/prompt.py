"""LLM instructions for Lease Accounting, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "lease_accounting/v1"

GUIDANCE = """\
Abstract the lease: lessor, leased asset, monthly payment, remaining term and the annual \
discount rate. Explain the engine's indicative figures: the present value of the remaining \
payments (paid at the end of each month) as the lease liability, the right-of-use asset \
(liability plus initial direct costs), and the total interest over the term. These are \
illustrations, not a certified ASC 842 / IFRS 16 schedule.
Summarise the renewal and termination options and the lease clauses only from the text the \
preparer entered, as a clause-review checklist; if none were entered, say so.

What the lease accounting reviewer should verify:
- the classification (finance or operating) against the signed lease
- the discount rate and where it came from
- whether renewal or termination options are reasonably certain to be exercised, which \
changes the term
- any change to an existing lease (a modification)

Never classify the lease yourself or state that entries were booked."""
