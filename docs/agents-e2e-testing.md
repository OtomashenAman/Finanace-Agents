# Agents: end-to-end testing guide

Manual end-to-end checks for the 12 agents. For what the steps and fields mean, see
[agents-user-guide.md](agents-user-guide.md). Every expected result below comes from
the engine tests in `tests/agent_catalog/` (same input gives the same result).

## Data source: one at a time

Use **one** data source per user while testing:

- **QuickBooks** (main path): Data Sources → Connect QuickBooks (sandbox company) → Sync now.
- **Upload** (only when QuickBooks isn't available): Data Sources → Upload file.

Don't connect QuickBooks and upload files for the same user at once. If you switch,
remove the old source first.

Ten agents read the data source:

| Agent | Pick a… | Also checks against the data |
|---|---|---|
| AP Invoice | bill | PO, vendor master; write-back to QuickBooks |
| Expense Audit | expense (card / cash / check) | the card charge itself, double charges |
| Cash Application | customer payment | the candidate invoice exists and is that customer's |
| AR Collections | customer | (prefill only: balance, aging, late history from invoices) |
| Treasury | *nothing*: enter a horizon (days) | overdue receivables (not counted in inflows) |
| Financial Close | *nothing*: choose account + month | books closing date |
| Board Reporting | *nothing*: choose a period | books closing date |
| FP&A | *nothing*: choose unit + period + metric | whether the data has a budget |
| Revenue Recognition | customer invoice (the contract) | the invoice is that customer's |
| Lease Accounting | rent bill | the monthly payment vs the lessor's latest bill |

The other 2 agents (Intercompany, SOX Controls) are manual input only, so they test the same
with either source, or with none. After a sync, the source card on Data Sources shows how many
records of each type came in.

**Month-end history** (needed by Financial Close, Board Reporting and FP&A) comes in the
background after each QuickBooks sync: 24 months of trial balances, AR/AP aging totals and
P&L, plus budgets and the books closing date. The source card shows *Fetching month-end
balances (24 months)…* and then the time it finished (and *books closed through …* if set).
Wait for that before testing those three agents. If it fails, the card shows the error; the
records from the sync are still there.

### What the QuickBooks sandbox has (checked on 21 Oct 2026)

The connected sandbox ("Sandbox Company US …") was checked against these parsers:
- **Trial balance:** 46 accounts, debits − credits = 0; A/R 20,431.52 = the AR aging total
  (reconciles)
- **AR / AP aging:** grand totals read correctly (customer sub-sections are not double counted)
- **P&L:** activity only from **March to July 2026** (July revenue 43,659.80). Other months
  are 0. **No classes**: only the company total (QuickBooks' "Not Specified" column, a copy of
  the total, is dropped)
- **No budget** and **no books closing date** are set

So in the sandbox: test Board Reporting and FP&A on 2026-03 … 2026-07 (or 2026-Q2); FP&A's
business unit list is only *Whole company*; the budget stays manual (`BUDGET_NOT_IN_DATA`);
the period checks don't appear until a closing date is set in QuickBooks (Settings → Advanced
→ Accounting → Close the books).

> Note: the app itself currently allows several sources per user and merges them for
> lookups (`src/app/data_sources/access.py`). "One at a time" is a testing rule for now,
> not something the app enforces.

## Common setup (once)

1. **Stack up:** `docker compose up --build`. The `migrate` service applies migrations
   before the backend and worker start.
2. **AI explanations:** set the Azure OpenAI values in `.env` (`LLM_PROVIDER`,
   `AZURE_OPENAI_*`). Without them the run still works, but the narrative card shows "AI
   explanations are turned off". The `worker` container must be running: it drafts the
   explanation in the background.
3. **Admin:** sign in as `finance.admin@example.com`.
4. **User:** Admin Settings → Users → create a user (role **User**). In *Agent access*, give
   them **preparer** on the agents. Or run `uv run poe seed`, which creates
   `demo.user@example.com` with every agent that has a workspace.
5. **Legal entity** (optional): with no entities, runs have no entity. If you add entities
   (Admin Settings → Entities), assign the user exactly one so "New analysis" picks it.
6. **Two tabs:** tab 1 admin, tab 2 user. In tab 2 click the **👤+** icon ("Use another
   account in this tab") **before** signing in as the user. Don't use Sign out for this:
   it would sign tab 1 out too.

## Common flow (every agent)

| Step | Who | Where | Check |
|---|---|---|---|
| 1 | User | Agent Catalog → agent → **New analysis** | Run `RUN-xxxxx` in status *Draft* |
| 2 | User | Fill the form (half-filled → **Save**) | Draft saves without all fields |
| 3 | User | **Validate & Analyze** with a required field empty | Status *Validation failed*, field error shown |
| 4 | User | Fill all fields, attach a file under *Source evidence* (PDF/XLSX/CSV/DOCX/TXT) | File listed, text extracted |
| 5 | User | **Validate & Analyze** | Headline, calculations, findings, then the AI explanation |
| 6 | User | **Submit for approval** (enabled once the explanation is ready) | *Pending approval*, input locked |
| 7 | Admin | Approvals / My Worklist → open run | Run listed with priority (High if any red finding) |
| 8 | Admin | Approve / Request changes / Reject (comment required) | Status changes, decision recorded |
| 9 | Both | Run → timeline, Audit Trail | Events: created, analyzed, submitted, reviewed |
| 10 | User | **Evidence pack** | ZIP with input, result, narrative, documents |

Also check:
- **Maker-checker:** the user who prepared the run sees no Approve / Reject buttons; only a
  Finance Admin decides.
- **Prompt version:** the narrative card shows e.g. `narrative/v1+treasury_cash/v1`.
- **Draft for review** (Expense Audit, AR Collections): the AI explanation has a "Draft for
  review · not sent" box. Nothing is ever sent; any figure in it that isn't in the data
  shows a guard warning.
- **Thresholds:** Admin Settings → Governance → change a threshold, re-analyze a new run,
  and the result follows the new version (the run shows `policy_version`).

---

## AP Invoice

**Data source:** yes (prefill from a bill, PO lookup, vendor master, write-back).

### Path A: QuickBooks

1. User tab: Data Sources → Connect QuickBooks (enter your QuickBooks app keys, authorize
   the sandbox company) → **Sync now**. Vendors, bills, purchase orders and accounts appear.
2. New analysis → *Prefill from your data* → pick a bill. Supplier, invoice number, total,
   tax and GL fill in. If the bill has a PO number and that PO exists, the PO amount and the
   received amount fill in too.
3. Fill the remaining fields → Validate & Analyze.
4. Check the vendor master finding:
   - vendor active in QuickBooks → `VENDOR_IN_MASTER` (pass)
   - vendor not found → `VENDOR_NOT_IN_MASTER` (warning)
   - vendor inactive → `VENDOR_INACTIVE` (high)
5. Approve as admin, then in the user tab:
   - run prefilled from a bill: write-back **stamps the approval on that QuickBooks bill**
     (private note)
   - run typed by hand: **Create bill in QuickBooks…** → pick company and expense account.
     The vendor must exist in QuickBooks; a second click doesn't create a duplicate.

### Path B: Upload (no QuickBooks)

Upload takes one record type per file ("What's in the file"), so use up to 3 small files.
Only the bills file is needed for prefill; the other two enable the PO match and the
vendor check.

`bills.csv`
```csv
id,invoice number,vendor,total,tax,po number,gl account
B-1,INV-2048,Acme Cloud Services,12500.00,0,PO-77,6100-Software
```
`purchase_orders.csv`
```csv
id,po number,vendor,total,received
P-1,PO-77,Acme Cloud Services,12500.00,12500.00
```
`vendors.csv`
```csv
id,name,active
V-1,Acme Cloud Services,true
```

Data Sources → Upload file → choose the type → check the column mapping and preview →
Upload. Then follow step 2 onwards of Path A. Write-back isn't available without
QuickBooks: the run shows "Connect QuickBooks on Data Sources to create this bill there."

### Test cases

| Case | Input | Expected |
|---|---|---|
| PDF example | supplier `Acme Cloud Services`, invoice `INV-2048`, total `12500`, PO `12500`, received `1000`, no GL, no file | **Invoice discrepancy**, High. `RECEIPT_MISMATCH` (differs by 11,500.00), `MISSING_GL`, `MISSING_EVIDENCE` |
| Clean | received `12500`, GL `6100-Software`, 1 file | **Invoice matches PO and receipt**, Normal, all pass |
| Over PO + tax | total `13000`, received `13000`, tax `14000` | `PO_MISMATCH`, `TAX_EXCEEDS_TOTAL` (both high) |
| Duplicate | analyze a second run with the same supplier and invoice number | **Duplicate invoice suspected**, `DUPLICATE_INVOICE` names the first run |
| Threshold | Governance: receipt tolerance `50`, high-value `10000`; received `12460` | `RECEIPT_MATCH` "within the 50.00 receipt tolerance", `HIGH_VALUE_INVOICE` |

---

## Expense Audit

**Data source:** expenses (QuickBooks *Purchase*: card, cash and check). Business reference =
employee.

**With QuickBooks:**
1. Admin: Governance → Expense Audit → *Policy limits by expense category* → add e.g.
   `Lodging` = `200` (the category is the expense account name in QuickBooks), and optionally a
   *Default policy limit*. Save.
2. User: New analysis → *Prefill from your data* → pick an expense. Check: merchant, amount,
   card transaction ID, *receipt provided* (ticked only if a file is attached to that purchase
   in QuickBooks) and the policy limit for its category.
3. Fill the employee if empty and the receipt total → Validate & Analyze.
4. Check the data findings: two purchases with the same merchant, amount and date →
   `DUPLICATE_CHARGE` (high); change the claim amount → `CLAIM_DIFFERS_FROM_CHARGE`.

**With an upload** (no QuickBooks), type *Expenses*:
```csv
Transaction ID,Date,Merchant,Amount,Category,Employee,Receipt
TX-501,2026-10-02,Northbridge Hotel,285.00,Lodging,Jordan Smith,yes
TX-502,2026-10-02,Northbridge Hotel,285.00,Lodging,Jordan Smith,no
```
Prefill from `TX-501` → policy limit from the Lodging limit, receipt provided ✔; analyze →
`DUPLICATE_CHARGE` (TX-502).

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | employee `Jordan Smith`, merchant `Northbridge Hotel`, claim `285`, limit `200`, receipt total `285`, receipt provided ✔, no file | **Policy exception**, High. Over limit 85.00. `POLICY_LIMIT_EXCEEDED` ("exceeds the 200.00 policy limit by 85.00"), `MISSING_EVIDENCE`. Draft asks the employee to explain |
| Clean | claim `180`, receipt total `180`, card transaction `TX-1`, 1 file | **Expense within policy**, Normal, all pass |
| No receipt | receipt provided ☐, receipt total empty, claim `150` | **Expense exception**, `MISSING_RECEIPT` (high) |
| Mismatch | claim `190`, receipt total `150` | `AMOUNT_MISMATCH` (high). With Governance receipt tolerance `1` and receipt `189.50`: `AMOUNT_RECONCILED` |
| Duplicate card | claim `150`, receipt `150`, card `tx-77`, prior IDs `TX-10, TX-77` | **Duplicate card transaction**, `DUPLICATE_CARD_TRANSACTION` (high). Also: a second analyzed run with the same card ID |

---

## AR Collections

**Data source:** customers + their invoices (QuickBooks *Customer*, *Invoice*, *Payment*).
Business reference = customer.

**With QuickBooks:** New analysis → *Prefill from your data* → pick a customer. Check:
- open balance = sum of the customer's open invoices
- days overdue = today − due date of the oldest open invoice
- previous late payments = invoices paid after their due date (QuickBooks: the last payment
  applied to the invoice is later than its due date)
- the source snapshot shows the oldest open invoice

Set dispute / strategic / promise yourself, then analyze. The draft reminder names the
customer.

**With an upload**, type *Customer invoices* (and *Customers* so there is a customer to pick):
```csv
Invoice No,Customer,Total,Balance,Invoice Date,Due Date,Paid Date
INV-8021,Harbor Distribution,1000.00,1000.00,2026-09-01,2026-09-30,
INV-8000,Harbor Distribution,500.00,0,2026-07-16,2026-08-15,2026-08-20
```
```csv
Name,Email
Harbor Distribution,ap@harbor.example
```
Prefill from Harbor Distribution → open balance 1,000.00, late payments 1, days overdue from
30 Sep 2026.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | customer `Harbor Distribution`, balance `25000`, days overdue `45`, late payments `2`, no dispute | **Collections priority**, Normal. Bucket 31-60, score 40 (30 + 10), next action *Send reminder*. `OVERDUE_AGING` (warning). Draft = payment reminder email |
| Dispute | days overdue `120`, open dispute ✔ | **Collections on hold: dispute**, `DISPUTE_BLOCK` + `OVERDUE_AGING` (high). Draft = internal note, not a reminder |
| Escalate | balance `80000`, days `75`, strategic ✔, promise `Pays on 30 Oct`, 1 file | **Escalate collection**, score 70 (50 + 10 + 10). `HIGH_EXPOSURE`, `STRATEGIC_ACCOUNT`, `PROMISE_TO_PAY` |
| Thresholds | Governance: reminder from `50`, escalate from `80`; PDF example | Next action *Monitor* (40 is under 50) |
| Not due | days overdue `0`, late payments `0` | **Monitor account**, `NOT_OVERDUE`, score 0 |

---

## Cash Application

**Data source:** customer payments + invoices (QuickBooks *Payment*, *Invoice*). Business
reference = payment reference.

**With QuickBooks:** New analysis → *Prefill from your data* → pick a payment. Check the
candidate invoice:
- a payment already applied to an invoice in QuickBooks → that invoice, *reference verified*
  ✔, open amount = its balance + what this payment applied
- an unapplied payment whose reference or memo names an open invoice of the customer → that
  invoice, verified ✔
- an unapplied payment matching exactly one open invoice's amount → proposed, verified ☐
- otherwise the invoice stays empty

Analyze → `INVOICE_IN_LEDGER` (pass). Change the customer to another one →
`INVOICE_CUSTOMER_MISMATCH` (high); type an invoice number that doesn't exist →
`INVOICE_NOT_FOUND`.

**With an upload**, types *Customer payments* and *Customer invoices*:
```csv
Date,Customer,Reference,Amount,Invoice No,Remittance
15/10/2026,Harbor Distribution,WIRE-2901,900.00,,Short paid INV-8021: damaged pallet
```
(invoices file as in AR Collections). Prefill from `WIRE-2901` → candidate INV-8021 (named in
the remittance), open 1,000.00 → **Short payment**, `DEDUCTION_REVIEW`.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | customer `Harbor Distribution`, reference `WIRE-2901`, payment `900`, invoice `INV-8021`, open amount `1000`, reference verified ✔ | **Short payment**, High. Short 100.00. `SHORT_PAYMENT`, `DEDUCTION_REVIEW` (high), `AMBIGUOUS_REMITTANCE`. Decision "Deduction requires classification" |
| Exact | payment `1000`, 1 file | **Payment matches invoice**, Normal, all pass |
| Small deduction | Governance: deduction review `250`; PDF example + remittance `Short paid: damaged pallet` + 1 file | `DEDUCTION_BELOW_THRESHOLD` (info), Normal |
| Overpayment | payment `1100`, reference verified ☐ | **Overpayment**, `OVERPAYMENT` + `REFERENCE_NOT_VERIFIED` (warnings), short −100.00 |
| Duplicate | second analyzed run with reference `WIRE-2901` | **Payment already applied**, `DUPLICATE_PAYMENT` (high) |

---

## Financial Close

**Data source:** month-end trial balance + AR/AP aging totals. Business reference = GL
account.

**With QuickBooks** (after the month-end history is ready): New analysis → *Prefill from your
data* → choose *GL account* and *Close period* → **Prefill**. Check:
- *Accounts Receivable (A/R)*: GL balance = the trial balance at that month end, subledger =
  the AR aging total (in the sandbox both are 20,431.52 for 2026-09 → **Account reconciled**
  once materiality is entered and a file attached)
- *Accounts Payable (A/P)*: GL balance shown **positive** (credit), subledger = the AP aging
  total
- a bank or other account: GL balance only, subledger left for you; the snapshot says
  "Not in the data for this account type"
- with a books closing date in QuickBooks: a month after it → `PERIOD_NOT_CLOSED`, on or
  before it → `PERIOD_CLOSED`

**With an upload:** types *Account balances by month* and *AR / AP subledger totals by month*:
```csv
Account,Account Number,Type,Period,Balance
Accounts Receivable (A/R),1200,Accounts Receivable,2026-09,120000.00
Accounts Payable (A/P),2000,Accounts Payable,2026-09,-49000.00
```
```csv
Ledger,Period,Total
AR,2026-09,119000.00
AP,2026-09,49000.00
```
Balances are debit-positive (a payable is negative, as in a trial balance). Prefill A/R
2026-09 → GL 120,000.00, subledger 119,000.00 → with materiality 500: **Material close
variance**. No closing date with uploads, so no period check.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | GL account `1200-AR-Control`, period `2026-09`, GL `120000`, subledger `119000`, materiality `500`, no file | **Material close variance**, High. Variance 1,000.00. `BALANCE_MISMATCH`, `MATERIAL_VARIANCE` ("exceeds the 500.00 materiality threshold"), `MISSING_RATIONALE`, `MISSING_EVIDENCE` |
| Fully explained | reconciling items `1000`, 1 file | **Account reconciled**, Normal. "Known reconciling items explain the 1,000.00 difference in full" |
| Immaterial | reconciling items `700`, rationale `Bank fee not yet booked`, 1 file | **Immaterial close variance**. 300.00 unexplained, `WITHIN_MATERIALITY` |
| Bad period | period `2026-13` | Field error on Close period (on Save or Analyze) |
| Duplicate | second analyzed run, same GL account and period | **Reconciliation already prepared**, `DUPLICATE_RECONCILIATION` |

Also check: `PREPARER_REVIEWER_SEPARATION` shows as info. The approval matrix routes on the
absolute variance.

---

## Intercompany

**Data source:** not used (manual input). Business reference = sending entity.

| Case | Input | Expected |
|---|---|---|
| PDF example | sending `US Subsidiary`, receiving `UK Subsidiary`, currency `USD`, AR `50000`, AP `49000`, rate `1`, tolerance `100` | **Intercompany mismatch**, High. Difference 1,000.00, available to net 49,000.00. `IC_MISMATCH`, `TRANSFER_PRICING_REVIEW`. Decision "Resolve before settlement" |
| FX match | AP `40000`, rate `1.2512`, notes `Cost plus 5%`, 1 file | Translated AP 50,048.00 (48.00 within tolerance): `IC_MATCH`, `FX_ASSUMPTION` (warning). **Intercompany match needs review** |
| Same entity | receiving `us subsidiary`, AP `50000` | **Intercompany exception**, `SAME_ENTITY` (high) |
| Bad rate | rate `0` or `1.123456789` | Field error on Translation rate |

---

## FP&A

**Data source:** monthly P&L (actual) and budget, by business unit. Business reference =
business unit.

**With QuickBooks:** New analysis → *Prefill from your data* → *Business unit*, *Forecast
period*, *Metric* → **Prefill**. Check actual = the metric added up over the period for that
unit, budget = the same from the QuickBooks budget. In the sandbox: *Whole company*, `2026-07`,
*Revenue* → actual 43,659.80, budget empty (no budget) → analyze shows `BUDGET_NOT_IN_DATA`.
To test budgets, create one in QuickBooks (Plus/Advanced: Settings → Budgeting) and sync again.

**With an upload:** type *Profit and loss by month*:
```csv
Period,Business Unit,Basis,Revenue,COGS,Operating Expenses
2026-07,,Actual,100000,30000,20000
2026-07,East,Actual,60000,18000,12000
2026-07,,Budget,90000,0,18000
2026-07,East,Budget,54000,0,0
```
(empty business unit = whole company; operating profit is calculated if not given). East,
2026-07, Revenue → actual 60,000.00, budget 54,000.00. Whole company, Operating profit →
50,000.00 vs 72,000.00.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | unit `North America`, period `Q4 2026`, actual `120000`, budget `100000`, volume `5`, price `2`, cost `3` | **Budget variance**, High. Variance 20,000.00 (20%). Scenario: +6,000 / +2,520 / −3,600 → 124,920.00. `VARIANCE_MATERIAL`, `MISSING_ASSUMPTIONS` |
| Within budget | actual `104000`, assumptions filled, 1 file | **Within budget tolerance**, Normal, `ASSUMPTION_APPROVAL` (info) |
| Thresholds | Governance: variance materiality `25`; price `-30` | `VARIANCE_WITHIN_THRESHOLD` (20% < 25%), `UNUSUAL_SCENARIO` (−30% beyond 25%) |
| No budget | budget `0` | `NO_BUDGET` (warning), variance % empty |

---

## Treasury

**Data source:** bank balances + open invoices + open bills, over a horizon (no record to
pick). The entity is the run's legal entity, not a field.

**With QuickBooks:** New analysis → *Prefill from your data* → horizon `30` → **Prefill**. Check:
- opening cash = the balances of the QuickBooks **Bank** accounts
- expected inflows = open invoices due between today and today + 30 (or with no due date)
- expected outflows = open bills due by today + 30, **overdue bills included**
- the snapshot lists the bank accounts, invoices due, overdue invoices (not counted) and bills
  due, with a summary

Enter currency and buffer → analyze. If the data has overdue invoices →
`OVERDUE_RECEIVABLES` (warning). *Prefill again* with horizon `5` → the totals change and the
run goes back to draft.

**With an upload:** three files, types *Chart of accounts*, *Customer invoices* and *Bills*
(use due dates a few days after today):
```csv
Name,Type,Balance
Operating Account,Bank,250000.00
Cloud Hosting,Expense,
```
```csv
Invoice No,Customer,Total,Balance,Due Date
INV-9001,Quiet Customer,400.00,400.00,<today + 10 days>
INV-8021,Harbor Distribution,1000.00,1000.00,2026-09-30
```
```csv
Bill No,Vendor,Total,Balance,Due Date
INV-2048,Acme Cloud Services,12500.00,12500.00,<today + 20 days>
```
Prefill with 30 days → opening 250,000.00, inflows 400.00 (INV-8021 is overdue: not counted),
outflows 12,500.00.

**Manual cases:**


| Case | Input | Expected |
|---|---|---|
| PDF example | currency `USD`, opening `250000`, inflows `150000`, outflows `300000`, buffer `125000`, horizon `30`, no file | **Liquidity shortfall**, High. Closing cash 100,000.00, funding gap 25,000.00. `LIQUIDITY_BUFFER` (high), `DUAL_AUTHORIZATION`, `NO_FUNDING_OPTIONS`, `MISSING_EVIDENCE` |
| Negative cash | outflows `450000`, funding options `Revolver` | **Negative cash projected**. Closing −50,000.00, gap 175,000.00. `NEGATIVE_PROJECTED_CASH` + `LIQUIDITY_BUFFER` |
| Buffer held | outflows `200000`, 1 file | **Liquidity within buffer**, Normal, all pass, gap 0.00 |
| Thresholds | Governance: dual authorization `50000`, large outflow `250000`; PDF example + funding options + 1 file | No `DUAL_AUTHORIZATION` (25k gap is under 50k), `LARGE_OUTFLOWS` warning |

Also check: the approval matrix routes on the **funding gap** (Governance → approval matrix,
amount label "Funding gap").

---

## Revenue Recognition

**Data source:** customer invoices (QuickBooks *Invoice*). QuickBooks has no contract object,
so an invoice stands in for the contract. Business reference = contract ID.

**With QuickBooks:** first **Sync now** (invoices synced before 22 Oct 2026 have no line items
or service dates). New analysis → *Prefill from your data* → pick an invoice. Check:
- customer, contract ID (= invoice number) and contract total (= invoice total, tax included)
- performance obligations = the invoice's product/service lines, one `item: amount` per line
- service term = months from the first to the last line **service date**; empty if the lines
  have none (in QuickBooks: Settings → Account and settings → Sales → *Service date* on)

Analyze → `CONTRACT_INVOICE_FOUND` (pass). Change the customer → `INVOICE_CUSTOMER_MISMATCH`
(high). An invoice with two or more lines → `MULTIPLE_OBLIGATIONS` (high).

**With an upload**, type *Customer invoices*:
```csv
Invoice No,Customer,Total,Line Items,Service Start,Service End
CTR-2026-091,Futura Technologies,120000.00,Hosting: 90000.00; Support: 30000.00,2026-01-01,2026-12-01
```
Prefill → term 12, obligations `Hosting: 90000.00; Support: 30000.00` → **Allocation across
obligations needed**.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | customer `Futura Technologies`, contract `CTR-2026-091`, total `120000`, term `12`, obligations `Hosting and support`, no file | **Allocation across obligations needed**, High. Monthly 10,000.00, 2 obligations. `MULTIPLE_OBLIGATIONS` (high), `FIXED_CONSIDERATION`, `POLICY_REVIEW`, `MISSING_CONTRACT_CLAUSES`, `MISSING_EVIDENCE`, `PRELIMINARY_ILLUSTRATION` (info). Decision "Needs obligation and policy review" |
| Clean | total `60000`, obligations `Hosting`, clauses `12-month hosting`, 1 file | **Single-obligation contract**, Normal, pass + info only. Decision "Revenue controller sign-off required" |
| Rounding | total `100000`, term `3` | Monthly 33,333.33, final month 33,333.34 |
| Variable + change | variable consideration `Usage fees above 1 TB; amended in month 6` | `VARIABLE_CONSIDERATION` + `CONTRACT_CHANGES` (warnings) |
| Same contract again | second analyzed run with contract `CTR-2026-091` | `CONTRACT_ANALYZED_BEFORE` (warning) |
| Threshold | Governance: revenue policy review empty | No `POLICY_REVIEW` |

Also check: the approval matrix routes on the **contract total**.

---

## Lease Accounting

**Data source:** bills (QuickBooks *Bill*): pick a **rent bill**. QuickBooks has no lease
object, but the lessor bills the rent. Business reference = leased asset.

**With QuickBooks:** New analysis → *Prefill from your data* → pick the rent bill. Check:
lessor = the bill's vendor, monthly payment = the bill total; everything else stays empty
(it comes from the lease agreement). Enter asset `Headquarters space`, term `24`, rate `6` →
analyze → `PAYMENT_MATCHES_BILLS` (pass, compared with the lessor's **latest** bill). Change
the payment → `PAYMENT_DIFFERS_FROM_BILLS`; change the lessor to one with no bills →
`NO_LESSOR_BILLS`.

**With an upload**, type *Bills*:
```csv
Bill No,Vendor,Total,Date,Account
RENT-09,Central Offices,5000.00,2026-09-01,Rent
RENT-10,Central Offices,5000.00,2026-10-01,Rent
```
Prefill from `RENT-10` → lessor *Central Offices*, payment 5,000.00.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | lessor `Central Offices`, asset `Headquarters space`, payment `5000`, term `24`, rate `6`, no file | **Lease schedule**, Normal. Liability 112,814.33, right-of-use asset 112,814.33, total payments 120,000.00, interest 7,185.67. `LEASE_CLASSIFICATION` (info), `DISCOUNT_RATE_IN_RANGE`, `NO_OPTIONS_RECORDED`, `NO_EARLIER_RUN`, `MISSING_LEASE_CLAUSES`, `MISSING_EVIDENCE`. Decision "Classification and assumptions need review" |
| Direct costs | initial direct costs `2500` | Right-of-use asset 115,314.33 (liability unchanged) |
| No rate | rate `0` | **Lease assumptions incomplete**, High. `NO_DISCOUNT_RATE`, liability 120,000.00, interest 0.00 |
| Odd rate | rate `18` | `DISCOUNT_RATE_OUT_OF_RANGE` (warning) |
| Short term | term `9` | **Short-term lease**, `SHORT_TERM_LEASE` (info) |
| Same lease again | second analyzed run, same lessor and asset | `LEASE_MODIFICATION` (warning) |
| Threshold | Governance: short-term lease empty; term `9` | No `SHORT_TERM_LEASE` |

Also check: the approval matrix routes on the **lease liability**.

---

## SOX Controls

**Data source:** not used (manual input). Business reference = control ID.

| Case | Input | Expected |
|---|---|---|
| PDF example | control `SOX-AP-003`, owner `AP Controller`, population `100`, tested `25`, exceptions `2`, no evidence | **Control exceptions found**, High. Exception rate 8.00%, coverage 25.00%. `EXCEPTIONS_ABOVE_TOLERABLE`, `MISSING_EVIDENCE_LINEAGE`, `MISSING_TEST_PROCEDURE` |
| Clean | exceptions `0`, evidence refs `SharePoint /SOX/AP-003/2026-Q3`, procedure `Reperform three-way match` | **Control operating effectively**, Normal |
| Bad sample | population `20`, tested `25`, exceptions `30` | `SAMPLE_EXCEEDS_POPULATION` + `EXCEPTIONS_EXCEED_SAMPLE` (high), coverage 125.00% |
| Thresholds | Governance: tolerable exceptions `2`; tested `10`, 1 file | **Control test needs completion**. `SAMPLE_TOO_SMALL` (minimum 25), `EXCEPTIONS_TOLERABLE` |
| Small population | population `10`, tested `10`, exceptions `0` | `SAMPLE_WITHIN_BOUNDS` (whole population tested) |
| Decimal count | tested `4.5` | Field error on Items tested (whole numbers only) |

Also check: the AI explanation doesn't call the result a deficiency or material weakness
(guidance in `sox_controls/prompt.py`).

---

## Board Reporting

**Data source:** monthly P&L (company total). Business reference = report name.

**With QuickBooks:** New analysis → *Prefill from your data* → *Reporting period* (months,
then complete quarters and years) → **Prefill**. Check reported revenue and operating profit =
the period's months added up, prior period revenue = the same period last year, and *Source
dataset / approval ID* filled with the source and sync time. In the sandbox: `2026-Q2` →
revenue 5,849.72 (Apr 521.00 + May 942.00 + Jun 4,386.72), prior 2025-Q2 = 0.00 →
`NO_PRIOR_PERIOD`. A year whose previous year isn't fully in the 24 months leaves the prior
revenue empty (the snapshot says why). Enter the report name, then analyze.

**With an upload:** the same *Profit and loss by month* file as FP&A (company rows with an
empty business unit), covering the period and the same period last year.

**Manual cases:**

| Case | Input | Expected |
|---|---|---|
| PDF example | report `Q3 Board Pack`, period `2026-Q3`, revenue `1000000`, prior `900000`, operating profit `150000`, no source ID | **Source references missing**, High. "Revenue increased by" 100,000.00, growth 11.11%, margin 15.00%. `MISSING_SOURCE_REFERENCE`, `NO_DISCLOSURES_RECORDED`, `MISSING_EVIDENCE` |
| Clean | + source ID `CLOSE-2026-09-APPROVED`, disclosures `No subsequent events`, 1 file | **Board figures consistent**, Normal, `SOURCE_REFERENCED` |
| Inconsistent | source `SRC-1`, revenue `500000`, profit `600000`; Governance: revenue change `20` | **Board figures inconsistent**. `PROFIT_EXCEEDS_REVENUE` (high), `UNUSUAL_REVENUE_CHANGE` (−44.44%), "Revenue decreased by" |
| No prior period | source `SRC-1`, prior `0` | `NO_PRIOR_PERIOD`, growth empty |

Also check: the AI explanation doesn't add reasons or forecasts that aren't in the input
(guidance in `board_reporting/prompt.py`).

---

## Automated tests

The same cases run in CI:

```bash
uv run pytest tests/agent_catalog -q
```

- `test_<agent>_engine.py`: each agent's rules and calculations
- `test_agents_api.py`: every agent except AP Invoice through the API (draft → validation
  failed → analyze → submit → approve), including the drafts
- `test_runs_api.py`, `tests/data_sources/`: AP Invoice, including QuickBooks prefill and
  write-back (with a fake QuickBooks), and the sync of customers, invoices, payments and
  expenses
- `test_data_source_prefill.py`: Cash Application, Expense Audit and AR Collections prefilled
  from the fake QuickBooks, the candidate invoice rules, category limits and aging
- `test_treasury_prefill.py`: Treasury's cash position (what is and isn't counted) and the
  prefill from parameters, end to end
- `test_financial_close_prefill.py`: trial balance and aging parsing, the 24-month window,
  account/period choices, AR vs aging, AP sign, and a failed history sync
- `test_contract_prefill.py`: Revenue Recognition from an invoice's lines and service dates,
  Lease Accounting from a rent bill, and their checks against the fake QuickBooks
- `test_reporting_prefill.py`: periods (month/quarter/year, last year), P&L by class and
  budget parsing, Board quarter vs last year, FP&A by unit and metric, no budget
