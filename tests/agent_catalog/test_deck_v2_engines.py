"""Rules added for the QuickBooks design deck (v2): one test per business example."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ap_invoice.agent import match_lines
from src.app.agent_catalog.agents.board_reporting.agent import BoardReportingAgent
from src.app.agent_catalog.agents.fpa_forecast.agent import FpaForecastAgent
from src.app.agent_catalog.agents.periods import comparison_basis, previous_period
from src.app.agent_catalog.agents.revenue_recognition.agent import (
    RevenueRecognitionAgent,
    months_elapsed,
)
from src.app.agent_catalog.agents.treasury_cash.agent import TreasuryCashAgent, cash_position
from src.app.data_sources.providers.quickbooks import _bill_payment, _doc_lines, _journal_lines
from src.app.data_sources.records import Account, Bill, DocLine, Invoice
from tests.agent_catalog.engine import calculation, codes, run_analysis
from tests.agent_catalog.test_board_reporting_engine import PDF_EXAMPLE as BOARD
from tests.agent_catalog.test_fpa_forecast_engine import PDF_EXAMPLE as FPA
from tests.agent_catalog.test_revenue_recognition_engine import PDF_EXAMPLE as REVREC
from tests.agent_catalog.test_treasury_cash_engine import PDF_EXAMPLE as TREASURY

# --- periods --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "previous"),
    [("2026-09", "2026-08"), ("2026-01", "2025-12"), ("2026-Q1", "2025-Q4"), ("2026", "2025")],
)
def test_previous_period(period: str, previous: str) -> None:
    assert previous_period(period) == previous


def test_comparison_basis_tells_month_on_month_from_year_on_year() -> None:
    assert comparison_basis("2026-09", "2026-08") == "period on period"
    assert comparison_basis("2026-09", "2025-09") == "year on year"
    assert comparison_basis("2026-09", None) is None
    assert comparison_basis("2026-09", "2024-01") is None


# --- Board: September $500,000 vs August $400,000 --------------------------------------------


async def test_board_states_month_on_month_growth(db: AsyncSession) -> None:
    values = {**BOARD, "reporting_period": "2026-09", "reported_revenue": "500000",
              "prior_period_revenue": "400000", "operating_profit": "100000",
              "comparison_period": "2026-08", "source_dataset_id": "Close 2026-09"}  # fmt: skip
    analysis = await run_analysis(db, BoardReportingAgent, values)
    labels = {c.key: c.label for c in analysis.calculations}
    assert labels["revenue_growth_pct"] == "Revenue growth (period on period)"
    assert calculation(analysis, "revenue_growth_pct") == Decimal("25.00")
    assert "COMPARISON_UNCLEAR" not in codes(analysis)


async def test_board_asks_which_period_prior_revenue_covers(db: AsyncSession) -> None:
    analysis = await run_analysis(db, BoardReportingAgent, {**BOARD, "comparison_period": None})
    assert codes(analysis)["COMPARISON_UNCLEAR"] == "warning"


# --- Treasury: the day-by-day low point ------------------------------------------------------


async def test_cash_that_dips_below_the_buffer_mid_horizon_is_a_shortfall(
    db: AsyncSession,
) -> None:
    # Closing cash 300,000 clears the 125,000 buffer, but on 2026-11-05 cash is 90,000
    values = {**TREASURY, "expected_outflows": "100000", "lowest_projected_cash": "90000",
              "lowest_cash_date": "2026-11-05"}  # fmt: skip
    analysis = await run_analysis(db, TreasuryCashAgent, values)
    found = codes(analysis)
    assert found["LIQUIDITY_BUFFER"] == "high"
    assert calculation(analysis, "funding_gap") == Decimal("35000.00")
    message = next(f.message for f in analysis.findings if f.code == "LIQUIDITY_BUFFER")
    assert "on 2026-11-05" in message and "recovers" in message


async def test_without_a_daily_low_the_closing_cash_is_used(db: AsyncSession) -> None:
    analysis = await run_analysis(db, TreasuryCashAgent, TREASURY)
    assert calculation(analysis, "funding_gap") == Decimal("25000.00")  # the deck's example


def test_daily_low_pays_bills_before_receipts_arrive() -> None:
    today = date(2026, 11, 1)
    bank = Account(external_id="1", name="Bank", account_type="Bank", current_balance="250000")
    bills = [Bill(external_id="b", doc_number="B", vendor_name="V", total="200000",
                  due_date=date(2026, 11, 5))]  # fmt: skip
    invoices = [Invoice(external_id="i", doc_number="I", customer_name="C", total="150000",
                        due_date=date(2026, 11, 20))]  # fmt: skip
    position = cash_position([bank], invoices, bills, today, 30)
    assert position.daily_low(today, 30) == (Decimal("50000.00"), date(2026, 11, 5))


# --- Revenue recognition: $120,000 over 12 months, 3 delivered -------------------------------


async def test_earned_and_deferred_to_date(db: AsyncSession) -> None:
    values = {**REVREC, "performance_obligations": "Hosting", "months_delivered": "3"}
    analysis = await run_analysis(db, RevenueRecognitionAgent, values)
    assert calculation(analysis, "earned_to_date") == Decimal("30000.00")
    assert calculation(analysis, "deferred_revenue") == Decimal("90000.00")


async def test_a_finished_term_has_earned_everything(db: AsyncSession) -> None:
    values = {**REVREC, "contract_total": "100", "service_term_months": "3",
              "months_delivered": "5"}  # fmt: skip
    analysis = await run_analysis(db, RevenueRecognitionAgent, values)
    assert calculation(analysis, "earned_to_date") == Decimal("100.00")  # not 33.33 x 3
    assert calculation(analysis, "deferred_revenue") == Decimal("0.00")


def test_months_elapsed_counts_whole_months() -> None:
    assert months_elapsed(date(2026, 7, 15), date(2026, 10, 14)) == 2
    assert months_elapsed(date(2026, 7, 15), date(2026, 10, 15)) == 3
    assert months_elapsed(date(2026, 12, 1), date(2026, 10, 1)) == 0


# --- FP&A: revenue vs cost behaviour ---------------------------------------------------------


async def test_revenue_scenario_is_unchanged(db: AsyncSession) -> None:
    analysis = await run_analysis(db, FpaForecastAgent, {**FPA, "metric": "Revenue"})
    assert calculation(analysis, "scenario_value") == Decimal("124920.00")
    message = next(f.message for f in analysis.findings if f.code == "VARIANCE_MATERIAL")
    assert "favourable" in message and "unfavourable" not in message


async def test_a_cost_grows_with_volume_and_cost_change_not_price(db: AsyncSession) -> None:
    values = {**FPA, "metric": "Operating expenses"}
    analysis = await run_analysis(db, FpaForecastAgent, values)
    # 120,000 + 5% volume (6,000) + 3% cost on 126,000 (3,780); the 2% price is left out
    assert calculation(analysis, "scenario_value") == Decimal("129780.00")
    assert calculation(analysis, "price_impact") == Decimal("0")
    found = codes(analysis)
    assert found["PRICE_NOT_APPLIED"] == "info"
    message = next(f.message for f in analysis.findings if f.code == "VARIANCE_MATERIAL")
    assert "unfavourable" in message  # spending 20% over budget


async def test_the_metric_must_be_stated(db: AsyncSession) -> None:
    analysis = await run_analysis(db, FpaForecastAgent, {**FPA, "metric": None})
    assert codes(analysis)["METRIC_NOT_STATED"] == "warning"


# --- AP: line-level three-way match ----------------------------------------------------------


def line(item: str, qty: str | None, price: str | None, amount: str) -> DocLine:
    return DocLine(item=item, quantity=qty, unit_price=price, amount=amount)


PO_LINES = [line("Compute hours", "100", "100", "10000"), line("Storage TB", "10", "250", "2500")]


def line_codes(findings: list[Any]) -> dict[str, str]:
    return {f.code: f.severity.value for f in findings}


def test_lines_matching_the_po_pass() -> None:
    bill = [line("compute hours", "100", "100", "10000"), line("Storage TB", "10", "250", "2500")]
    assert line_codes(match_lines(bill, PO_LINES, "PO-77", Decimal(0))) == {"LINES_MATCH": "pass"}


def test_a_line_billed_above_the_po_price_or_quantity_is_an_exception() -> None:
    bill = [line("Compute hours", "120", "100", "12000"), line("Storage TB", "10", "260", "2600")]
    findings = match_lines(bill, PO_LINES, "PO-77", Decimal(0))
    found = line_codes(findings)
    assert found["LINE_QUANTITY_OVER"] == "high"
    assert found["LINE_PRICE_DIFFERS"] == "high"
    price = next(f.message for f in findings if f.code == "LINE_PRICE_DIFFERS")
    assert "260.00 vs 250.00" in price and "100.00 on 10 units" in price


def test_an_item_not_on_the_po_and_po_lines_not_billed_yet() -> None:
    bill = [line("Compute hours", "100", "100", "10000"), line("Support", None, None, "500")]
    found = line_codes(match_lines(bill, PO_LINES, "PO-77", Decimal(0)))
    assert found["LINE_NOT_ON_PO"] == "high"
    assert found["PO_LINES_NOT_BILLED"] == "info"  # storage: a later invoice may bill it


def test_account_lines_compare_amounts_within_the_tolerance() -> None:
    po = [line("Cloud Hosting", None, None, "12500")]
    assert line_codes(match_lines([line("Cloud Hosting", None, None, "12550")], po, "PO-1",
                                  Decimal(50))) == {"LINES_MATCH": "pass"}  # fmt: skip
    over = match_lines([line("Cloud Hosting", None, None, "12600")], po, "PO-1", Decimal(50))
    assert line_codes(over) == {"LINE_AMOUNT_OVER": "high"}


def test_quickbooks_item_lines_keep_quantity_and_price() -> None:
    row = {"Line": [
        {"Amount": 10000.0, "ItemBasedExpenseLineDetail": {
            "ItemRef": {"value": "5", "name": "Compute hours"}, "Qty": 100, "UnitPrice": 100}},
        {"Amount": 2500.0, "AccountBasedExpenseLineDetail": {
            "AccountRef": {"value": "7", "name": "6100 Cloud Hosting"}}},
        {"Amount": 12500.0, "DetailType": "SubTotalLineDetail"},
    ]}  # fmt: skip
    assert [(x.item, x.quantity, x.unit_price, x.amount) for x in _doc_lines(row)] == [
        ("Compute hours", Decimal("100"), Decimal("100"), Decimal("10000.00")),
        ("6100 Cloud Hosting", None, None, Decimal("2500.00")),
    ]


# --- QuickBooks mapping ----------------------------------------------------------------------


def test_bill_payment_names_the_bills_it_paid() -> None:
    paid = [{"Amount": 12500.0, "LinkedTxn": [{"TxnId": "145", "TxnType": "Bill"}]}]
    acme = {"value": "56", "name": "Acme"}
    row = {"Id": "900", "DocNumber": "CHK-4410", "VendorRef": acme, "TotalAmt": 12500.0,
           "TxnDate": "2026-10-20", "PayType": "Check", "Line": paid}  # fmt: skip
    payment = _bill_payment(row, {"145": "INV-2048"})
    assert payment.bills_paid == "INV-2048" and payment.pays("inv-2048")
    assert payment.total == Decimal("12500.00")


def test_journal_entry_becomes_signed_lines() -> None:
    row = {"Id": "77", "DocNumber": "JE-1005", "TxnDate": "2026-09-30", "Line": [
        {"Id": "0", "Amount": 1000.0, "Description": "Reclass",
         "JournalEntryLineDetail": {"PostingType": "Debit",
                                    "AccountRef": {"value": "84", "name": "Accounts Receivable"}}},
        {"Id": "1", "Amount": 1000.0,
         "JournalEntryLineDetail": {"PostingType": "Credit",
                                    "AccountRef": {"value": "79", "name": "Sales"}}},
    ]}  # fmt: skip
    lines = _journal_lines(row)
    assert [(line.account, line.amount_signed) for line in lines] == [
        ("Accounts Receivable", Decimal("1000.00")),
        ("Sales", Decimal("-1000.00")),
    ]
    assert {line.external_id for line in lines} == {"77-0", "77-1"}
