"""LLM instructions for AP Invoice, appended to the shared system prompt (runs/prompts.py).

Bump PROMPT_VERSION whenever GUIDANCE changes: narratives record it for the audit trail.
"""

PROMPT_VERSION = "ap_invoice/v1"

GUIDANCE = """\
Explain the three-way match between invoice, purchase order and receipt: say which amounts \
agree, which differ and by how much, using the calculated differences.
Cover any duplicate risk (an earlier run with the same supplier and invoice number) and any \
vendor master result.
Point out missing coding (no proposed GL account) or missing evidence.

What the AP approver should verify in the source documents:
- the invoice number, date and total on the supplier invoice
- the PO authorized amount and the goods or services actually received
- that tax on the invoice is consistent with its total
- the proposed GL account fits what was bought

Do not choose or suggest a GL account the preparer did not enter."""
