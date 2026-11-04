"""Finance POD: procure-to-pay with agents and people in the loop (GIA Accounts Payable).

Phase 1 runs a purchase request to an issued purchase order. Agents prepare (enrich a
request, check the budget, source vendors, onboard a vendor, draft the PO); people decide
(budget owner, buyer, AP analyst, second approver). Finance Admins only, like the Service
POD, but each decision records the capacity it was given in, and separation-of-duties rules
hold between different admin accounts unless the Finance POD settings allow self-approval.

Guardrails enforced in code, not just in the flow:
- no PO without an approved request
- bank details are never taken from email
- nobody approves a request they raised; a vendor is verified and activated by two people
"""
