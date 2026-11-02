"""The people the requirement's future-state slides name ("Who"), as capacities a Finance
Admin grants. A step names the capacity that completes it; a sign-off names the capacity it
is given in."""

from enum import StrEnum


class FinanceCapacity(StrEnum):
    # Procure-to-Pay
    REQUESTER = "requester"
    BUDGET_OWNER = "budget_owner"
    BUYER = "buyer"
    RECEIVER = "receiver"
    AP_ANALYST = "ap_analyst"
    VENDOR_APPROVER = "vendor_approver"  # the second person who activates a new vendor
    GRANTS_ACCOUNTANT = "grants_accountant"
    CONTROLLER = "controller"
    TREASURY = "treasury"
    # Order-to-Cash
    CREDIT_CONTROLLER = "credit_controller"
    BILLING_ANALYST = "billing_analyst"
    CASH_TEAM = "cash_team"
    FINANCE_LEAD = "finance_lead"


LABELS: dict[FinanceCapacity, tuple[str, str]] = {
    FinanceCapacity.REQUESTER: ("Requester", "Raises purchase requests (lab, campus, department)."),
    FinanceCapacity.BUDGET_OWNER: ("Budget owner", "Approves, rejects or queries requests."),
    FinanceCapacity.BUYER: ("Buyer", "Chooses vendors and terms; approves POs above the limit."),
    FinanceCapacity.RECEIVER: ("Receiver", "Confirms goods and services received."),
    FinanceCapacity.AP_ANALYST: (
        "AP analyst",
        "Reviews low-confidence reads, calls back to confirm bank details.",
    ),
    FinanceCapacity.VENDOR_APPROVER: (
        "Vendor approver",
        "The second person who activates a new vendor.",
    ),
    FinanceCapacity.GRANTS_ACCOUNTANT: ("Grants accountant", "Confirms flagged grant charges."),
    FinanceCapacity.CONTROLLER: (
        "Controller",
        "Approves above limit; reviews and signs off the close.",
    ),
    FinanceCapacity.TREASURY: ("Treasury", "Reviews and releases payment runs."),
    FinanceCapacity.CREDIT_CONTROLLER: (
        "Credit controller",
        "Approves credit terms; decides holds and plans.",
    ),
    FinanceCapacity.BILLING_ANALYST: (
        "Billing analyst",
        "Reviews flagged invoices; approves overrides.",
    ),
    FinanceCapacity.CASH_TEAM: ("Cash team", "Confirms unmatched cash or contacts the client."),
    FinanceCapacity.FINANCE_LEAD: ("Finance lead", "Approves credits and write-offs."),
}


def label(capacity: str) -> str:
    try:
        return LABELS[FinanceCapacity(capacity)][0]
    except ValueError:
        return capacity.replace("_", " ").capitalize()
