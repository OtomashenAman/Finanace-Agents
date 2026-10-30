"""What the AI is told when it reads a customer's reply (versioned with each reading)."""

READ_PROMPT_VERSION = "ar_reply/v1"


READ_SYSTEM = (
    "You read a customer's reply about overdue invoices and return JSON only. Report only "
    "what the customer wrote: copy their exact words into each quote. Never invent amounts, "
    "dates or invoice numbers. If a payment has no calendar date, set date to null. Use only "
    "the invoice numbers listed. For dates without a year, use the next such date on or after "
    "the reply date."
)
