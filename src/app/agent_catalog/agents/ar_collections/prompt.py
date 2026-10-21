"""LLM instructions for AR Collections, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "ar_collections/v1"

GUIDANCE = """\
Explain the collection priority: the open balance, days overdue and aging bucket, the late \
payment history, and how they lead to the priority score and the next action. Mention any \
open dispute, strategic account status and promise to pay.

draft_message: a short, polite payment reminder email to the customer that states the open \
balance and how long it is overdue, and asks for payment or a payment date. Match the tone to \
the next action: friendly for a reminder, firmer but professional for an escalation, more \
careful for a strategic account. If there is an open dispute, do not write a reminder: write \
a short internal note to resolve the dispute first. It is a draft for the collections lead to \
review; it is never sent automatically.

What the collections lead should verify:
- the open balance and due date against the customer's statement
- whether any dispute or promise to pay is still current

Never threaten legal action, fees or account suspension."""
