"""LLM instructions for Expense Audit, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "expense_audit/v1"

GUIDANCE = """\
Explain the expense audit result: the claim against the policy limit, whether a receipt was \
provided and whether its total reconciles to the claim, and any duplicate card transaction.

draft_message: a short, polite clarification request to the employee that names the merchant \
and the specific issues found (over limit, missing receipt, amount mismatch, duplicate) and \
asks for an explanation or the missing receipt. If no issue was found, a brief note that the \
claim is within policy. It is a draft for the finance auditor to review; it is never sent \
automatically.

What the finance auditor should verify:
- the receipt matches the merchant, date and amount claimed
- the policy limit used applies to this expense category
- the card transaction hasn't been claimed before

Do not accuse the employee of misconduct; describe the facts only."""
