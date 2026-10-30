from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
    Prefill,
)
from src.app.agent_catalog.agents.checks import (
    ZERO,
    evidence_check,
    has_severity,
    missing,
    money,
    over_limit,
)
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.agents.treasury_cash import prompt
from src.app.agent_catalog.agents.treasury_cash.models import TreasuryCashRun
from src.app.agent_catalog.agents.treasury_cash.schemas import (
    TreasuryCashInput,
    TreasuryCashPolicy,
    TreasuryPrefillParams,
)
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.common.clock import utcnow
from src.app.data_sources.access import FinanceData
from src.app.data_sources.records import Account, Bill, Invoice, RecordType


@dataclass(frozen=True)
class CashPosition:
    """Cash over a horizon, from bank balances and open invoices and bills."""

    banks: list[Account]  # bank accounts with a known balance
    invoices_due: list[Invoice]  # open, due within the horizon (or with no due date)
    overdue_invoices: list[Invoice]  # open and already past due: not counted
    bills_due: list[Bill]  # open, due by the end of the horizon, overdue included

    @property
    def opening_cash(self) -> Decimal:
        return sum((a.current_balance or ZERO for a in self.banks), ZERO)

    @property
    def inflows(self) -> Decimal:
        return sum((i.open_amount for i in self.invoices_due), ZERO)

    @property
    def overdue_receivables(self) -> Decimal:
        return sum((i.open_amount for i in self.overdue_invoices), ZERO)

    @property
    def outflows(self) -> Decimal:
        return sum((b.open_amount for b in self.bills_due), ZERO)

    def daily_low(self, today: date, horizon_days: int) -> tuple[Decimal, date]:
        """The lowest end-of-day cash within the horizon, and its first day.

        Conservative timing: bills overdue or without a due date go out today, invoices
        without a due date come in on the last day, and each day's payments leave before its
        receipts arrive. Each invoice and bill counts once.
        """
        end = today + timedelta(days=horizon_days)
        flows: dict[date, Decimal] = {}
        for bill in self.bills_due:
            day = max(bill.due_date or today, today)
            flows[day] = flows.get(day, ZERO) - bill.open_amount
        for invoice in self.invoices_due:
            day = invoice.due_date or end
            flows[day] = flows.get(day, ZERO) + invoice.open_amount
        balance = low = self.opening_cash
        low_day = today
        for day in sorted(flows):
            balance += flows[day]
            if balance < low:
                low, low_day = balance, day
        return low, low_day


def cash_position(
    accounts: list[Account],
    invoices: list[Invoice],
    bills: list[Bill],
    today: date,
    horizon_days: int,
) -> CashPosition:
    """Conservative: receivables already overdue aren't counted (collection is uncertain),
    payables already overdue are (they still have to be paid)."""
    end = today + timedelta(days=horizon_days)
    banks = [
        a
        for a in accounts
        if (a.account_type or "").lower() == "bank" and a.current_balance is not None
    ]
    open_invoices = [i for i in invoices if i.open_amount > ZERO]
    return CashPosition(
        banks=banks,
        invoices_due=[i for i in open_invoices if i.due_date is None or today <= i.due_date <= end],
        overdue_invoices=[i for i in open_invoices if i.due_date and i.due_date < today],
        bills_due=[
            b for b in bills if b.open_amount > ZERO and (b.due_date is None or b.due_date <= end)
        ],
    )


def _closing_cash(data: TreasuryCashInput) -> Decimal:
    return data.opening_cash + data.expected_inflows - data.expected_outflows


def _low_point(data: TreasuryCashInput) -> Decimal:
    """The lowest cash the horizon reaches: the daily low when known, else closing cash."""
    closing = _closing_cash(data)
    low = data.lowest_projected_cash
    return closing if low is None else min(low, closing)


def _funding_gap(data: TreasuryCashInput) -> Decimal:
    """How much must be funded to stay at the buffer every day (0 when the buffer holds)."""
    return max(data.minimum_liquidity_buffer - _low_point(data), ZERO)


class TreasuryCashAgent(BaseAgent):
    key = "treasury_cash"
    code = "08"
    name = "Treasury Cash Forecasting & Liquidity"
    short_name = "Treasury"
    description = "Forecast end cash and detect shortfalls before funds movement."
    primary_user = "Treasury Analyst"
    reviewer = "Treasury Approver"

    input_schema = TreasuryCashInput
    run_model = TreasuryCashRun
    policy_version = "treasury_cash/v1"
    controls = (
        "Liquidity buffer",
        "Negative projected cash",
        "Dual authorization",
        "Bank signatories",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    policy_schema = TreasuryCashPolicy
    approval_amount_label = "Funding gap"
    prefill_params = TreasuryPrefillParams

    @classmethod
    async def autofill_params(
        cls, values: dict[str, Any], data: FinanceData
    ) -> dict[str, Any] | None:
        """The horizon entered (else the default), when there are balances, invoices or bills."""
        if not any(
            [
                await data.has(RecordType.ACCOUNT),
                await data.has(RecordType.INVOICE),
                await data.has(RecordType.BILL),
            ]
        ):
            return None
        horizon = values.get("forecast_horizon_days")
        return {"forecast_horizon_days": horizon} if horizon else {}

    @classmethod
    async def prefill_from_data(
        cls, params: BaseModel, data: FinanceData, policy: PolicySettings | None = None
    ) -> Prefill:
        horizon = cast(TreasuryPrefillParams, params).forecast_horizon_days
        today = utcnow().date()
        accounts = await data.records(Account, RecordType.ACCOUNT)
        invoices = await data.records(Invoice, RecordType.INVOICE)
        bills = await data.records(Bill, RecordType.BILL)
        position = cash_position(accounts, invoices, bills, today, horizon)

        values: dict[str, object] = {"forecast_horizon_days": horizon}
        # Only what the data supports: no bank balances means opening cash stays for the preparer
        if position.banks:
            values["opening_cash"] = position.opening_cash
        if invoices:
            values["expected_inflows"] = position.inflows
        if bills:
            values["expected_outflows"] = position.outflows
        low, low_day = position.daily_low(today, horizon)
        if position.banks and (invoices or bills):
            values["lowest_projected_cash"] = low
            values["lowest_cash_date"] = low_day.isoformat()
        return Prefill(
            values,
            reference=f"Next {horizon} days from {today:%d %b %Y}",
            summary={
                "as_of": today,
                "horizon_days": horizon,
                "bank_accounts": len(position.banks),
                "opening_cash": position.opening_cash,
                "invoices_due": len(position.invoices_due),
                "expected_inflows": position.inflows,
                "overdue_receivables_not_counted": position.overdue_receivables,
                "bills_due": len(position.bills_due),
                "expected_outflows": position.outflows,
                "lowest_daily_cash": low,
                "lowest_cash_date": low_day,
                "opening_cash_basis": "Book (GL) balance of bank accounts: confirm the available "
                "bank cash with a bank statement",
            },
            lines={
                "bank_accounts": position.banks,
                "invoices_due": position.invoices_due,
                "overdue_invoices": position.overdue_invoices,
                "bills_due": position.bills_due,
            },
        )

    @staticmethod
    async def _receivables_checks(ctx: AnalysisContext) -> list[Finding]:
        """Overdue receivables in the preparer's data: not counted, but worth knowing."""
        if not await ctx.data.has(RecordType.INVOICE):
            return []
        invoices = await ctx.data.records(Invoice, RecordType.INVOICE)
        today = utcnow().date()
        overdue = [
            i for i in invoices if i.open_amount > ZERO and i.due_date and i.due_date < today
        ]
        if not overdue:
            return []
        total = sum((i.open_amount for i in overdue), ZERO)
        return [
            Finding(
                "OVERDUE_RECEIVABLES",
                FlagSeverity.WARNING,
                f"{money(total)} of receivables ({len(overdue)} invoice"
                f"{'' if len(overdue) == 1 else 's'}) is already overdue: not counted in "
                "prefilled inflows; confirm before relying on it",
                "expected_inflows",
            )
        ]

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return _funding_gap(cast(TreasuryCashInput, data))

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        cash = cast(TreasuryCashInput, data)
        policy = cast(TreasuryCashPolicy, ctx.policy) if ctx.policy else TreasuryCashPolicy()
        closing = _closing_cash(cash)
        low = _low_point(cash)
        gap = _funding_gap(cash)
        buffer = cash.minimum_liquidity_buffer
        findings: list[Finding] = []
        # The trough, when it is below closing cash: cash dips before it recovers
        dips = low < closing
        when = f" on {cash.lowest_cash_date}" if dips and cash.lowest_cash_date else ""
        what = f"Lowest daily cash{when}" if dips else "Projected closing cash"
        field = "lowest_projected_cash" if dips else "expected_outflows"

        if low < ZERO:
            findings.append(
                Finding(
                    "NEGATIVE_PROJECTED_CASH",
                    FlagSeverity.HIGH,
                    f"{what} is negative ({money(low)}) within "
                    f"{cash.forecast_horizon_days} days"
                    + (f", before recovering to {money(closing)}" if dips else ""),
                    field,
                )
            )
        else:
            findings.append(
                Finding(
                    "PROJECTED_CASH_POSITIVE",
                    FlagSeverity.PASS,
                    f"Projected cash stays positive (lowest {money(low)})",
                    field,
                )
            )

        if gap > ZERO:
            findings.append(
                Finding(
                    "LIQUIDITY_BUFFER",
                    FlagSeverity.HIGH,
                    f"{what} {money(low)} is {money(gap)} below the {money(buffer)} minimum "
                    "liquidity buffer"
                    + (f" (closing cash {money(closing)} recovers)" if dips else ""),
                    "minimum_liquidity_buffer",
                )
            )
            dual = over_limit(
                gap,
                policy.dual_authorization_amount,
                code="DUAL_AUTHORIZATION",
                message=(
                    f"Funding the {money(gap)} gap needs dual authorization by the bank "
                    "signatories before any funds move"
                ),
                field="minimum_liquidity_buffer",
            )
            no_options = missing(
                cash.permitted_funding_options,
                code="NO_FUNDING_OPTIONS",
                message="No permitted funding options recorded for the shortfall",
                field="permitted_funding_options",
            )
            findings.extend(f for f in (dual, no_options) if f is not None)
        else:
            findings.append(
                Finding(
                    "LIQUIDITY_BUFFER_MET",
                    FlagSeverity.PASS,
                    f"Projected cash covers the {money(buffer)} minimum liquidity buffer every "
                    f"day (headroom {money(low - buffer)})",
                    "minimum_liquidity_buffer",
                )
            )

        findings.extend(await cls._receivables_checks(ctx))
        optional_checks = [
            over_limit(
                cash.expected_outflows,
                policy.large_outflow_amount,
                code="LARGE_OUTFLOWS",
                message=(
                    f"Expected outflows exceed the {money(policy.large_outflow_amount or ZERO)} "
                    "review limit: confirm their timing"
                ),
                field="expected_outflows",
            ),
            evidence_check(ctx, "bank statements or cash forecast"),
        ]
        findings.extend(f for f in optional_checks if f is not None)

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if low < ZERO:
            headline = "Negative cash projected"
        elif gap > ZERO:
            headline = "Liquidity shortfall"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Liquidity projection needs review"
        else:
            headline = "Liquidity within buffer"

        calculations = [
            Calculation("opening_cash", "Opening cash", cash.opening_cash),
            Calculation("expected_inflows", "Expected inflows", cash.expected_inflows),
            Calculation("expected_outflows", "Expected outflows", cash.expected_outflows),
            Calculation("closing_cash", "Projected closing cash", closing),
        ]
        if cash.lowest_projected_cash is not None:
            calculations.append(
                Calculation(
                    "lowest_projected_cash", "Lowest daily cash", cash.lowest_projected_cash
                )
            )
            if cash.lowest_cash_date:
                calculations.append(
                    Calculation(
                        "lowest_cash_date", "Lowest cash date", cash.lowest_cash_date, "text"
                    )
                )
        return Analysis(
            headline=headline,
            proposed_decision=(
                "Check buffer limits before action"
                if exceptions
                else "Treasury approver sign-off required"
            ),
            calculations=[
                *calculations,
                Calculation("minimum_liquidity_buffer", "Minimum liquidity buffer", buffer),
                Calculation("funding_gap", "Funding gap", gap),
                Calculation(
                    "forecast_horizon_days",
                    "Forecast horizon (days)",
                    str(cash.forecast_horizon_days),
                    "number",
                ),
            ],
            findings=findings,
            computed={"closing_cash": closing, "funding_gap": gap},
        )
