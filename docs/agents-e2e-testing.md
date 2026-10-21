# Agents: end-to-end testing guide

Manual end-to-end checks for the 10 agents that have a workspace. For what the steps and fields mean, see
[agents-user-guide.md](agents-user-guide.md). Every expected result below comes from
the engine tests in `tests/agent_catalog/` (same input gives the same result).

## Data source: one at a time

Use **one** data source per user while testing:

- **QuickBooks** (main path): Data Sources → Connect QuickBooks (sandbox company) → Sync now.
- **Upload** (only when QuickBooks isn't available): Data Sources → Upload file.

Don't connect QuickBooks and upload files for the same user at once. If you switch,
remove the old source first.

Four agents read the data source:

| Agent | Pick a… | Also checks against the data |
|---|---|---|
| AP Invoice | bill | PO, vendor master; write-back to QuickBooks |
| Expense Audit | expense (card / cash / check) | the card charge itself, double charges |
| Cash Application | customer payment | the candidate invoice exists and is that customer's |
| AR Collections | customer | (prefill only: balance, aging, late history from invoices) |

The other 6 agents are manual input only, so they test the same with either source, or with
none. After a sync, the source card on Data Sources shows how many records of each type came
in (vendors, bills, purchase orders, accounts, customers, invoices, payments, expenses).

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

**Data source:** not used (manual input). Business reference = GL account.

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

**Data source:** not used (manual input). Business reference = business unit.

| Case | Input | Expected |
|---|---|---|
| PDF example | unit `North America`, period `Q4 2026`, actual `120000`, budget `100000`, volume `5`, price `2`, cost `3` | **Budget variance**, High. Variance 20,000.00 (20%). Scenario: +6,000 / +2,520 / −3,600 → 124,920.00. `VARIANCE_MATERIAL`, `MISSING_ASSUMPTIONS` |
| Within budget | actual `104000`, assumptions filled, 1 file | **Within budget tolerance**, Normal, `ASSUMPTION_APPROVAL` (info) |
| Thresholds | Governance: variance materiality `25`; price `-30` | `VARIANCE_WITHIN_THRESHOLD` (20% < 25%), `UNUSUAL_SCENARIO` (−30% beyond 25%) |
| No budget | budget `0` | `NO_BUDGET` (warning), variance % empty |

---

## Treasury

**Data source:** not used (manual input). The entity is the run's legal entity, not a field.

| Case | Input | Expected |
|---|---|---|
| PDF example | currency `USD`, opening `250000`, inflows `150000`, outflows `300000`, buffer `125000`, horizon `30`, no file | **Liquidity shortfall**, High. Closing cash 100,000.00, funding gap 25,000.00. `LIQUIDITY_BUFFER` (high), `DUAL_AUTHORIZATION`, `NO_FUNDING_OPTIONS`, `MISSING_EVIDENCE` |
| Negative cash | outflows `450000`, funding options `Revolver` | **Negative cash projected**. Closing −50,000.00, gap 175,000.00. `NEGATIVE_PROJECTED_CASH` + `LIQUIDITY_BUFFER` |
| Buffer held | outflows `200000`, 1 file | **Liquidity within buffer**, Normal, all pass, gap 0.00 |
| Thresholds | Governance: dual authorization `50000`, large outflow `250000`; PDF example + funding options + 1 file | No `DUAL_AUTHORIZATION` (25k gap is under 50k), `LARGE_OUTFLOWS` warning |

Also check: the approval matrix routes on the **funding gap** (Governance → approval matrix,
amount label "Funding gap").

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

**Data source:** not used (manual input). Business reference = report name.

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
