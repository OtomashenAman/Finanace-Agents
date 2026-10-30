"""The five Service POD workflows: who works on them and which source data they need.

Phase 1 holds the shared contract only; each workflow's own steps, calculations and checks
plug into the case engine later through the hooks on WorkflowSpec.
"""

from dataclasses import dataclass
from enum import StrEnum

from src.app.service_pod.snapshots.contract import Collection

C = Collection


class WorkflowKey(StrEnum):
    AR_COLLECTIONS = "ar_collections"
    BANK_RECON = "bank_recon"
    FPA_TREND = "fpa_trend"
    TREASURY = "treasury"
    REPORTING = "reporting"


class Capacity(StrEnum):
    PREPARER = "preparer"  # opens cases, drafts messages, imports replies
    REVIEWER = "reviewer"  # approves messages, commitments, results (first gate)
    FINAL_APPROVER = "final_approver"  # independent final sign-off (CFO)
    POSTER = "poster"  # Finance Admin: imports sources, performs and verifies manual posting


@dataclass(frozen=True)
class WorkflowSpec:
    key: WorkflowKey
    name: str
    prefix: str  # case references: AR-0042
    description: str
    # Deck role names, for screens and the assignments page
    labels: dict[Capacity, str]
    required: frozenset[Collection]  # a case can't start on a snapshot without these
    visible: frozenset[Collection]  # what its users may read of a snapshot
    final_gate: bool  # True: a different user gives the final approval after the review

    @property
    def capacities(self) -> tuple[Capacity, ...]:
        return tuple(self.labels)


WORKFLOWS: dict[WorkflowKey, WorkflowSpec] = {
    spec.key: spec
    for spec in (
        WorkflowSpec(
            key=WorkflowKey.AR_COLLECTIONS,
            name="AR Collections",
            prefix="AR",
            description=(
                "Customer conversations on overdue invoices: approved emails, reply "
                "understanding, supported payment commitments."
            ),
            labels={
                Capacity.PREPARER: "AR user",
                Capacity.REVIEWER: "AR Reviewer",
                Capacity.POSTER: "Finance Admin",
            },
            required=frozenset({C.CUSTOMERS, C.INVOICES}),
            visible=frozenset({C.CUSTOMERS, C.INVOICES, C.PAYMENTS, C.CONTRACTS}),
            final_gate=False,
        ),
        WorkflowSpec(
            key=WorkflowKey.BANK_RECON,
            name="Bank-to-Invoice Reconciliation",
            prefix="BNK",
            description=(
                "Cleared bank receipts allocated to invoices on customer instructions, posted "
                "manually and verified against a fresh export."
            ),
            labels={
                Capacity.PREPARER: "Cash Analyst",
                Capacity.REVIEWER: "Cash Reviewer",
                Capacity.POSTER: "Finance Admin",
            },
            required=frozenset({C.CUSTOMERS, C.INVOICES, C.PAYMENTS, C.BANK_RECEIPTS}),
            visible=frozenset({C.CUSTOMERS, C.INVOICES, C.PAYMENTS, C.BANK_RECEIPTS}),
            final_gate=False,
        ),
        WorkflowSpec(
            key=WorkflowKey.FPA_TREND,
            name="FP&A Trend Intelligence",
            prefix="FPA",
            description=(
                "Month-by-month P&L trends reconciled to posted transactions, with cited "
                "drivers and Finance Head commentary."
            ),
            labels={
                Capacity.PREPARER: "FP&A Analyst",
                Capacity.REVIEWER: "Finance Head",
                Capacity.POSTER: "Finance Admin",
            },
            required=frozenset({C.ACCOUNTS, C.GL_LINES, C.TRANSACTIONS}),
            visible=frozenset({C.ACCOUNTS, C.GL_LINES, C.TRANSACTIONS, C.INVOICES}),
            final_gate=False,
        ),
        WorkflowSpec(
            key=WorkflowKey.TREASURY,
            name="Treasury Forecast",
            prefix="TRS",
            description=(
                "A 13-week cash view from bank-verified cash, approved receipt schedules and "
                "approved outflows, with scenarios and owned mitigations."
            ),
            labels={
                Capacity.PREPARER: "Treasury Analyst",
                Capacity.REVIEWER: "Treasury Head",
                Capacity.FINAL_APPROVER: "CFO",
            },
            required=frozenset({C.CASH_POSITION, C.INVOICES, C.PLANNED_OUTFLOWS}),
            visible=frozenset(
                {
                    C.CASH_POSITION,
                    C.INVOICES,
                    C.CUSTOMERS,
                    C.CONTRACTS,
                    C.PLANNED_OUTFLOWS,
                    C.BANK_RECEIPTS,
                }
            ),
            final_gate=True,
        ),
        WorkflowSpec(
            key=WorkflowKey.REPORTING,
            name="Financial Reporting",
            prefix="RPT",
            description=(
                "The monthly management pack: comparable statements, balance checks, cited "
                "commentary, Controller review and CFO sign-off."
            ),
            labels={
                Capacity.PREPARER: "Reporting Analyst",
                Capacity.REVIEWER: "Controller",
                Capacity.FINAL_APPROVER: "CFO",
                Capacity.POSTER: "Finance Admin",
            },
            required=frozenset(
                {
                    C.ACCOUNTS,
                    C.GL_LINES,
                    C.TRANSACTIONS,
                    C.BALANCE_SHEETS,
                    C.CLOSE_STATUS,
                    C.INVOICES,
                }
            ),
            visible=frozenset(
                {
                    C.ACCOUNTS,
                    C.GL_LINES,
                    C.TRANSACTIONS,
                    C.BALANCE_SHEETS,
                    C.CLOSE_STATUS,
                    C.INVOICES,
                    C.CUSTOMERS,
                }
            ),
            final_gate=True,
        ),
    )
}
