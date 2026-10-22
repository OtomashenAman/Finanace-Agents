# Sample uploads (no QuickBooks)

Ready-to-upload files to run every agent from uploaded data. They use the same values as
[agents-e2e-testing.md](../agents-e2e-testing.md).

**Before you start:** remove the QuickBooks source on Data Sources. Use one source at a time:
with QuickBooks still connected, lookups may read QuickBooks instead of these files.

## One file for every agent (recommended)

`all-agents.xlsx` has one sheet per type, named after it. Data Sources → Upload file → *What's
in the file*: **Several types, one sheet each (XLSX)** → pick the file. Each sheet shows the
type it was recognized as (change it, or *Skip this sheet*), its row counts, and under
*Columns and preview* its column mapping. → **Import**: all sheets become **one** data source.
Nothing is imported if a sheet has a problem (unless you tick *skip the rows with problems*).

Sheet names that are recognized include the type's label (e.g. *Customer invoices*) and common
names such as *Bills*, *Invoices*, *P&L*, *Trial balance*, *Chart of accounts*. Another name
reads as *pick a type*. Two sheets of the same type are refused: keep or skip one.

The workbook is built from the CSVs below: after changing a CSV, run
`uv run poe sample-workbook`.

## One file per type

The same data as separate CSVs. Data Sources → Upload file → pick the type below in *What's
in the file* → check the column mapping and preview → Import. Each file becomes its own data
source.

| File | Type to pick | Used by |
|---|---|---|
| `vendors.csv` | Vendors | AP Invoice (vendor check) |
| `bills.csv` | Bills (supplier invoices) | AP Invoice, Lease Accounting, Treasury |
| `purchase_orders.csv` | Purchase orders | AP Invoice (PO match) |
| `chart_of_accounts.csv` | Chart of accounts | Treasury (bank balance) |
| `customers.csv` | Customers | AR Collections |
| `customer_invoices.csv` | Invoices (customer invoices) | AR Collections, Cash Application, Treasury, Revenue Recognition |
| `customer_payments.csv` | Customer payments | Cash Application |
| `expenses.csv` | Expenses (card, cash, check) | Expense Audit |
| `account_balances.csv` | Account balances by month (trial balance) | Financial Close |
| `subledger_totals.csv` | AR / AP subledger totals by month | Financial Close |
| `profit_and_loss.csv` | Profit and loss by month (actual or budget) | FP&A, Board Reporting |

SOX Controls and Intercompany take no file: they are manual input only.

## What to pick in each agent

New analysis → *Prefill from your data*:

| Agent | Pick / enter | Prefill gives |
|---|---|---|
| AP Invoice | bill `INV-2048` | Acme Cloud Services, 12,500.00, tax 500.00, PO-77 (received 12,500.00), GL 6100 Cloud Hosting |
| Expense Audit | expense `TX-501` | Jordan Smith, Northbridge Hotel, 285.00, receipt provided. The policy limit comes from Governance (set a Lodging limit of 200) or enter `200` → `POLICY_LIMIT_EXCEEDED`, and `DUPLICATE_CHARGE` because of `TX-502` |
| AR Collections | customer `Harbor Distribution` | open balance 1,000.00, 1 late payment (INV-8000 paid 5 days late), days overdue from 30 Sep 2026 |
| Cash Application | payment `WIRE-2901` | candidate INV-8021 (named in the remittance), open 1,000.00 → short payment 100.00 |
| Revenue Recognition | invoice `CTR-2026-091` | Futura Technologies, 120,000.00, term 12, two obligations → *Allocation across obligations needed* |
| Lease Accounting | bill `RENT-10` | Central Offices, 5,000.00; enter asset, term `24`, rate `6` → matches the latest rent bill |
| Treasury | horizon `30` | opening cash 250,000.00; inflows and outflows from invoices and bills due in the next 30 days |
| Financial Close | account `Accounts Receivable (A/R)`, period `2026-09` | GL 120,000.00 vs subledger 119,000.00 |
| FP&A | unit `East`, period `2026-07`, metric revenue | actual 60,000.00, budget 54,000.00 |
| Board Reporting | period `2026-Q3` | revenue 315,000.00 vs 285,000.00 for 2025-Q3 |

## Things to know

- **Dates are fixed.** Treasury counts what is due between today and the horizon, so as the
  dates pass the totals change. Move `Due Date` in `bills.csv` and `customer_invoices.csv`
  forward to test again.
- **Without QuickBooks** there is no write-back of approved AP bills, and no books closing
  date, so the closed-period checks of Financial Close, FP&A and Board Reporting don't appear.
- **Balances are debit-positive** in `account_balances.csv`: a payable is negative, as in a
  trial balance.
- An empty *Business Unit* in `profit_and_loss.csv` means the whole company.
