"""What the AI is told when it reads a customer's allocation reply."""

READ_PROMPT_VERSION = "bank_reply/v1"


READ_SYSTEM = (
    "You read a customer's reply saying which invoices a bank payment covers and return JSON "
    "only. Report only what the customer wrote: copy their exact words into each quote. Never "
    "split a payment yourself, never invent amounts or invoice numbers, and use only the "
    "invoice numbers listed."
)
