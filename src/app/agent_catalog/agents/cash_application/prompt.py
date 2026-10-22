"""LLM instructions for Cash Application, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "cash_application/v1"

GUIDANCE = """\
Explain the proposed match of the payment to the candidate invoice: whether the reference was \
verified, the payment amount against the invoice open amount, and any short payment \
(possible deduction) or overpayment.
If there is a short payment, summarise what the remittance advice says about the reason; if \
there is no remittance advice, say the deduction reason is unknown. Do not classify the \
deduction yourself (pricing, damage, promotion, ...): the reviewer does.

What the cash application reviewer should verify:
- the bank receipt (amount, date, payer) and the payment reference
- that the invoice is open for the stated amount and belongs to this customer
- support for any deduction before it is accepted or disputed

Never state that cash was applied or posted in the ERP."""
