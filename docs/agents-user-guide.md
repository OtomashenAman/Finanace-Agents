# Agents: user guide

How a run works in the 10 agents that have a workspace: the 3 steps every run goes through,
how an agent processes your data, then for each agent its input fields and the exact rules it
applies. (Revenue Recognition and Lease Accounting don't have a workspace yet.)

For test values and expected results, see [agents-e2e-testing.md](agents-e2e-testing.md).

## Who does what

| Role | Does |
|---|---|
| **User** (preparer) | Starts a run, fills the input, attaches evidence, analyzes, submits |
| **Finance Admin** (reviewer) | Reviews submitted runs and decides: approve, request changes or reject |

The person who prepared a run can never approve it (maker-checker).

## The 3 steps

```
 1. INPUT  ──Validate & Analyze──▶  2. RESULT  ──Submit for approval──▶  3. REVIEW
 (user fills)                       (system calculates,                  (admin decides)
                                     user checks)
```

### Step 1: Input (user)

1. Agent Catalog → pick the agent → **New analysis**. A run `RUN-xxxxx` is created as *Draft*.
2. Fill the form. You can **Save** a half-filled form and come back later.
3. Under **Source evidence**, attach supporting files: PDF (text-based), XLSX, CSV, DOCX or
   TXT, up to 10 MB each. The app reads their text so the AI explanation can refer to them.
   With no file attached, the result shows a *missing evidence* warning.
4. Click **Validate & Analyze**. If a required field is empty or invalid, the run becomes
   *Validation failed* and the field shows the error.

Entering values:
- **Money:** `12500`, `12,500.00` and `$12,500` all work. At most 2 decimals.
- **Whole numbers:** days, months and counts take no decimals.
- **Percent:** enter `6` for 6%.
- Fields marked "(optional)" can stay empty.

You can still edit the input and analyze again while the run is *Draft*, *Validation
failed*, *Needs human review* or *Changes requested*.

### Step 2: Result (system calculates, user checks)

| Part | What it shows |
|---|---|
| **Headline** | The outcome in one line, e.g. "Liquidity shortfall" |
| **Priority** | **High** if any finding is high (red), otherwise Normal |
| **Calculations** | Every figure, calculated by the rules engine (never by the AI) |
| **Findings** | One line per check (see below) |
| **Review these controls** | The checklist the reviewer works through |
| **Proposed decision** | What the result suggests, e.g. "Resolve exceptions before approval" |
| **AI explanation** | Summary, key points, missing evidence and unclear points, written by Claude |
| **Draft for review** | Expense Audit and AR Collections only: a message drafted by Claude (an employee clarification, a payment reminder). It is **never sent**; copy it if you want to use it |

Finding severities:

| Severity | Meaning |
|---|---|
| ✅ Pass | The check is satisfied |
| ℹ️ Info | For information, e.g. "a different person must approve" |
| ⚠️ Warning | Something is incomplete; the reviewer should look |
| 🔴 High | An exception the reviewer must resolve before approving |

About the AI explanation:
- It only **explains** the result. It never calculates, changes a figure, approves, or
  suggests moving money.
- If it mentions a figure that isn't in the data (in the explanation or the draft), or cites
  a field or document that doesn't exist, a **guard warning** is shown.
- It records the AI model and the prompt version (e.g. `narrative/v1+treasury_cash/v1`), so
  you can always tell which instructions produced it.

When the explanation is ready, click **Submit for approval**. The run becomes *Pending
approval* and the input is locked.

### Step 3: Review (Finance Admin)

1. Open the run from **Approvals** or **My Worklist**. You see the input, calculations,
   findings, AI explanation and documents together.
2. Go through *Review these controls* and check the attached evidence.
3. Decide, with a comment (required, at least 3 characters):

| Decision | Run becomes | What happens next |
|---|---|---|
| **Approve** | Approved | Final. For AP Invoice, the user can write it back to QuickBooks |
| **Request changes** | Changes requested | The user edits, analyzes again and resubmits |
| **Reject** | Rejected | Final, the run is closed |

Every step is recorded in the **Audit Trail**. On approval the app saves a fingerprint
(hash) of exactly what was approved. **Evidence pack** downloads the whole run as a ZIP.

## Where the data comes from

A data source is your QuickBooks company (Data Sources → Connect QuickBooks) or files you
upload. A QuickBooks sync brings two kinds of data:

| Kind | What | When |
|---|---|---|
| **Records** | vendors, bills, purchase orders, accounts (with bank balances), customers, invoices, payments, expenses | right away, when you sync |
| **Month-end history** | for each of the last **24 complete months**: the trial balance, the AR and AP aging totals, and the profit and loss (by class), plus budgets and the books closing date | in the background after each sync (about 100 QuickBooks reports); the source card shows *Fetching month-end balances…* until it's done |

Two ways to prefill a run:
- **Pick one record** (AP Invoice: a bill; Expense Audit: an expense; Cash Application: a
  payment; AR Collections: a customer)
- **Enter parameters** and let the agent add up many records (Treasury: a horizon; Financial
  Close: an account and month; Board Reporting: a period; FP&A: a unit, period and metric)

Either way, the run keeps a **snapshot** of what was used (records, totals, the records behind
each total), so the reviewer sees exactly that, even if the data changes later.

## How an agent processes your data

What happens when you click **Validate & Analyze**, in order:

```
 your input ─▶ 1 validate ─▶ 2 load policy ─▶ 3 rules engine ─▶ 4 save result ─▶ 5 AI explanation
                  │ fail                         (Python)                         (background)
                  ▼
           Validation failed
```

1. **Validate.** The input is checked against the agent's field rules (required, type, range,
   format). Any error → status *Validation failed*, each error shown on its field, nothing
   else runs.
2. **Load the policy.** The admin's current thresholds for the agent (Governance) are loaded.
   Their version and values are saved on the run, so a later threshold change never changes
   an old result.
3. **Rules engine (Python, no AI).** The agent's `analyze()` runs its checks in a fixed order
   and returns:
   - **calculations**: every figure, using exact decimal arithmetic, rounded to cents where
     it's money
   - **findings**: one per check, each with a code, severity and message
   - **headline** and **proposed decision**: chosen by fixed rules from the findings
   - **priority**: High if any finding is 🔴 high, otherwise Normal

   Some checks also read context: how many documents are attached (missing evidence), your
   earlier runs (duplicate checks look only at **your own** runs that were analyzed, ignoring
   drafts and failed ones, and compare text without case), and for the agents that read your
   data source (AP Invoice, Expense Audit, Cash Application, AR Collections, Treasury,
   Financial Close, Board Reporting, FP&A) the matching records in it.
4. **Save.** Findings, calculations and the typed results are stored (each agent has its own
   table), the run becomes *Needs human review*, and an audit event is recorded.
5. **AI explanation (background worker).** Claude receives only: the validated input, the
   calculations, the findings, the headline and proposed decision, the legal entity, and the
   text of the attached documents (up to 15,000 characters each, 40,000 in total). It returns
   structured output (summary, key points, cited fields and documents, missing evidence,
   ambiguities, and a draft for agents that have one). It can only cite fields and documents
   that exist. Guard checks then flag any figure in its text that isn't in the data.

On **Submit for approval**, the app fingerprints (hashes) the input, policy, calculations,
findings, documents and AI explanation together: that is exactly what the reviewer approves.

### Common checks

Several agents share these building blocks:

| Check | Rule | Finding |
|---|---|---|
| Tolerance match | difference = 0 → match; \|difference\| ≤ tolerance → match ("within tolerance"); otherwise → mismatch | ✅ match / 🔴 mismatch |
| Over a limit | value > limit (an empty limit means the check is off) | usually ⚠️ |
| Missing input | an optional field that matters was left empty | ⚠️ |
| Missing evidence | no document attached | ⚠️ `MISSING_EVIDENCE` |
| Duplicate run | an earlier analyzed run of yours with the same key values | 🔴, naming that run |

---

## AP Invoice Intake, Coding & Approval

Checks a supplier invoice against its purchase order and what was received before it is paid.

| Field | Meaning | What you can enter |
|---|---|---|
| Supplier | Company that sent the invoice | Text, up to 200 characters, e.g. `Acme Cloud Services` |
| Invoice number | Number printed on the invoice | Text, up to 100, e.g. `INV-2048` |
| Invoice total | Total amount billed | Money, more than 0 |
| PO authorized amount | Amount approved on the purchase order | Money, 0 or more |
| Received amount | Value of goods or services actually received | Money, 0 or more |
| Tax total | Tax on the invoice | Money, optional |
| Proposed GL account | Expense account to book it to | Text, optional, e.g. `6100-Software` |

All fields are required unless marked optional.

**Prefill from your data:** pick a bill (QuickBooks or an uploaded bills file). Supplier, invoice number, total, tax and GL account come from the bill. If the bill has
a PO number and that PO is in your data, the PO amount and received amount come from the PO.
You complete the rest.

**How it works** (checks in order):

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Duplicate | Earlier run with the same supplier **and** invoice number | 🔴 `DUPLICATE_INVOICE` / ✅ `DUPLICATE_CHECK_CLEAR` |
| 2 | Vendor master | Only if your data source has vendors: supplier not found / inactive / active | ⚠️ `VENDOR_NOT_IN_MASTER` / 🔴 `VENDOR_INACTIVE` / ✅ `VENDOR_IN_MASTER` |
| 3 | PO match | Invoice total − PO amount, against the PO tolerance | ✅ `PO_MATCH` / 🔴 `PO_MISMATCH` |
| 4 | Receipt match | Invoice total − received amount, against the receipt tolerance | ✅ `RECEIPT_MATCH` / 🔴 `RECEIPT_MISMATCH` |
| 5 | High value | Invoice total > high-value limit (off by default) | ⚠️ `HIGH_VALUE_INVOICE` |
| 6 | Tax | Tax total > invoice total | 🔴 `TAX_EXCEEDS_TOTAL` |
| 7 | Coding | No proposed GL account | ⚠️ `MISSING_GL` |
| 8 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |

**Calculations:** invoice total, PO amount, received amount, tax (if given), invoice − PO,
invoice − received.

**Headline:** duplicate → *Duplicate invoice suspected*; any 🔴 → *Invoice discrepancy*; any ⚠️
→ *Invoice needs completion*; else *Invoice matches PO and receipt*.
**Proposed decision:** any 🔴 → *Resolve exceptions before approval*; else *AP reviewer
approval required*. **Approval matrix** routes on the invoice total.

**After approval:** a run prefilled from a QuickBooks bill can stamp the approval on that bill;
a run typed by hand can create the bill in QuickBooks.

**Reviewer checks:** the invoice, the PO, the proof of receipt and the GL coding.

## Expense Audit & Corporate Card Compliance

Checks an employee's expense or card claim against the policy limit and the receipt.

| Field | Meaning | What you can enter |
|---|---|---|
| Employee | Who made the claim | Text, e.g. `Jordan Smith` |
| Merchant | Where the money was spent | Text, e.g. `Northbridge Hotel` |
| Claim amount | Amount claimed | Money, more than 0 |
| Policy limit | Limit for this expense category | Money, 0 or more |
| Receipt total | Total printed on the receipt | Money, optional |
| Receipt provided | Was a receipt submitted | Checkbox |
| Card transaction ID | Corporate card transaction for this claim | Text, optional |
| Prior card transaction IDs | Transactions already claimed | Long text, optional: separate with commas or new lines |

**Prefill from your data:** pick an expense (QuickBooks card, cash or check purchase, or an
uploaded expenses file). Merchant, amount, card transaction ID and *receipt provided* (a file
is attached in QuickBooks) come from it, plus the employee when QuickBooks records one. The
**policy limit** comes from the admin's limits per expense category (the expense's account),
else the default limit. You enter the receipt total.

**How it works** (checks in order):

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Duplicate card | Only with a card transaction ID: is it in the prior IDs list? If not, was it in an earlier run? | 🔴 `DUPLICATE_CARD_TRANSACTION` / ✅ `DUPLICATE_CHECK_CLEAR` |
| 1a | Card data | Only with a card transaction ID **and** expenses in your data source: not found / claim ≠ the charge's amount / another charge with the same merchant, amount and date | ⚠️ `CARD_TRANSACTION_NOT_FOUND` / ⚠️ `CLAIM_DIFFERS_FROM_CHARGE` / 🔴 `DUPLICATE_CHARGE` |
| 2 | Receipt | Receipt provided ticked? | ✅ `RECEIPT_PROVIDED` / 🔴 `MISSING_RECEIPT` |
| 3 | Policy limit | Claim − policy limit > 0 | 🔴 `POLICY_LIMIT_EXCEEDED` (by how much) / ✅ `WITHIN_POLICY_LIMIT` |
| 4 | Reconciliation | With a receipt total: claim − receipt total, against the receipt tolerance. Receipt ticked but no total: can't reconcile | ✅ `AMOUNT_RECONCILED` / 🔴 `AMOUNT_MISMATCH` / ⚠️ `MISSING_RECEIPT_TOTAL` |
| 5 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |

**Calculations:** claim, policy limit, amount over the limit (0 if within), and with a
receipt total: receipt total, claim − receipt.

**Headline:** duplicate (either kind) → *Duplicate card transaction*; over the limit → *Policy exception*;
other 🔴 → *Expense exception*; any ⚠️ → *Expense needs completion*; else *Expense within
policy*. **Proposed decision:** any 🔴 → *Request explanation or reject*; else *Finance audit
approval required*. **Approval matrix** routes on the claim amount.

**Draft for review:** a clarification request to the employee about the issues found.

**Reviewer checks:** the receipt (merchant, date, amount) and that the limit fits the category.

## AR Collections Prioritization & Dunning

Scores an overdue customer balance and proposes the next collection action.

| Field | Meaning | What you can enter |
|---|---|---|
| Customer | Who owes the money | Text, e.g. `Harbor Distribution` |
| Open balance | Amount still unpaid | Money, more than 0 |
| Days overdue | Days past the due date | Whole number, 0 to 3650 (0 = not yet due) |
| Previous late payments | How often the customer paid late before | Whole number, 0 to 1000 |
| Open dispute | Customer disputes the balance | Checkbox |
| Strategic account | Key customer: handle with care | Checkbox |
| Promise to pay date / details | What the customer promised | Text, optional |
| Collection notes | Notes from earlier contact | Long text, optional |

**Prefill from your data:** pick a customer. From that customer's invoices (QuickBooks or an
uploaded invoices file):
- **open balance** = the sum of the open amounts of their invoices
- **days overdue** = today − the due date of the oldest open invoice (0 if none is past due)
- **previous late payments** = invoices that were paid after their due date

The oldest open invoice is kept in the run's source snapshot for the reviewer. Dispute,
strategic account and promise to pay aren't in QuickBooks: you set them.

**How it works:**

1. **Priority score (0–100)** from fixed points:

   | Part | Points |
   |---|---|
   | Days overdue: 0 / 1–30 / 31–60 / 61–90 / 90+ | 0 / 10 / 30 / 50 / 70 |
   | Open balance above the high exposure level (default 50,000) | +10 |
   | Each previous late payment | +5 (at most +20) |

2. **Next-best action:** an open dispute always → **Hold – resolve dispute**. Otherwise score
   ≥ escalate level (default 60) → **Escalate**; ≥ reminder level (default 30) → **Send
   reminder**; below → **Monitor**.
3. **Checks** (in order):

   | Check | Rule | Finding |
   |---|---|---|
   | Aging | 0 days / 1–90 days / over 90 days | ✅ `NOT_OVERDUE` / ⚠️ `OVERDUE_AGING` / 🔴 `OVERDUE_AGING` |
   | Exposure | Balance above the high exposure level | ⚠️ `HIGH_EXPOSURE` / ✅ `EXPOSURE_NORMAL` |
   | Dispute | Open dispute ticked | 🔴 `DISPUTE_BLOCK` / ✅ `NO_DISPUTE` |
   | Strategic | Strategic account ticked | ⚠️ `STRATEGIC_ACCOUNT` |
   | Promise | Promise to pay filled in | ℹ️ `PROMISE_TO_PAY` |
   | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |

**Calculations:** open balance, days overdue, aging bucket, late payments, priority score,
next-best action.

**Headline / proposed decision** follow the action: Hold → *Collections on hold: dispute* /
*Resolve the dispute before any dunning*; Escalate → *Escalate collection* / *Approve
escalation and the draft communication*; Reminder → *Collections priority* / *Draft reminder
for human approval*; Monitor → *Monitor account* / *No dunning now: reviewer confirms*.
The run's High/Normal priority is separate from the score: it is High only for a 90+ balance
or an open dispute. **Approval matrix** routes on the open balance.

**Draft for review:** a payment reminder email whose tone follows the action, or an internal
note to resolve the dispute when there is one.

**Reviewer checks:** the balance against the customer statement, and whether the dispute or
promise is still current.

## Cash Application & Deductions Resolution

Matches a customer payment to an open invoice and spots short payments (deductions).

| Field | Meaning | What you can enter |
|---|---|---|
| Customer | Who paid | Text |
| Payment/remittance reference | Bank reference of the payment, e.g. wire number | Text, e.g. `WIRE-2901` |
| Payment amount | Amount received | Money, more than 0 |
| Candidate invoice number | Invoice the payment is for | Text, e.g. `INV-8021` |
| Invoice open amount | Amount still open on that invoice | Money, more than 0 |
| Reference verified | The reference was checked against the invoice | Checkbox |
| Remittance advice | What the customer said about the payment | Long text, optional |

**Prefill from your data:** pick a customer payment (QuickBooks or an uploaded payments file).
Customer, reference, amount and memo (as remittance advice) come from it. The **candidate
invoice** is found in this order:

1. the invoice the payment is applied to in QuickBooks → *reference verified*; the open
   amount is the invoice's balance **plus** what this payment applied (its balance is already
   net of it)
2. otherwise, the one open invoice of that customer whose number appears in the reference or
   memo → *reference verified*
3. otherwise, the one open invoice of that customer for exactly the payment amount → proposed,
   *not* verified
4. otherwise none: you enter it

**How it works:** short payment = invoice open amount − payment (positive = paid too little,
negative = paid too much). Then, in order:

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Duplicate | Earlier run with the same payment reference | 🔴 `DUPLICATE_PAYMENT` / ✅ `DUPLICATE_CHECK_CLEAR` |
| 2 | Reference | Reference verified ticked? | ✅ `INVOICE_REFERENCE_MATCH` / ⚠️ `REFERENCE_NOT_VERIFIED` |
| 2a | Invoice data | Only with invoices in your data source: invoice not found / belongs to another customer / found for this customer | ⚠️ `INVOICE_NOT_FOUND` / 🔴 `INVOICE_CUSTOMER_MISMATCH` / ✅ `INVOICE_IN_LEDGER` |
| 3 | Amount | Difference 0 or within the match tolerance | ✅ `AMOUNT_MATCH` |
| | | Short beyond tolerance | ⚠️ `SHORT_PAYMENT`, plus 🔴 `DEDUCTION_REVIEW` if above the deduction review threshold, else ℹ️ `DEDUCTION_BELOW_THRESHOLD` |
| | | Overpaid beyond tolerance | ⚠️ `OVERPAYMENT` |
| 4 | Remittance | A difference beyond tolerance and no remittance advice | ⚠️ `AMBIGUOUS_REMITTANCE` |
| 5 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |

**Calculations:** payment amount, invoice open amount, invoice open − payment.

**Headline:** duplicate → *Payment already applied*; short → *Short payment*; overpaid →
*Overpayment*; any ⚠️ → *Cash match candidate*; else *Payment matches invoice*.
**Proposed decision:** deduction to review → *Deduction requires classification*; other 🔴 →
*Resolve exceptions before applying cash*; else *Cash application reviewer approval
required*. **Approval matrix** routes on the payment amount.

**Reviewer checks:** the bank receipt, that the invoice is open for that customer, and
support for any deduction.

## Financial Close & Account Reconciliation

Reconciles a GL account to its subledger at month end.

| Field | Meaning | What you can enter |
|---|---|---|
| GL account | Account being reconciled | Text, up to 100, e.g. `1200-AR-Control` |
| Close period | Month being closed | `YYYY-MM` only, e.g. `2026-09` |
| GL balance | Balance in the general ledger | Money, can be negative |
| Subledger balance | Balance in the detail ledger (e.g. AR) | Money, can be negative |
| Materiality threshold | Largest difference treated as minor | Money, 0 or more |
| Known reconciling items | Differences already identified (e.g. in transit) | Money, optional, can be negative |
| Proposed adjustment rationale | Why the difference exists and how to fix it | Long text, optional |

**Prefill from your data:** choose a **GL account** and a **close period** (both lists come
from your month-end history). Then:
- **GL balance** = the account's trial balance at that month end. Accounts Payable is shown
  **credit-positive** (the trial balance has it as a negative debit) so it compares with the
  AP aging total; the snapshot says which sign is used.
- **Subledger balance** = the AR aging total (Accounts Receivable) or the AP aging total
  (Accounts Payable) at that month end. Other accounts have no subledger in QuickBooks: you
  enter it.

Materiality, reconciling items and rationale stay for you.

**How it works:** variance = GL − subledger; unexplained difference = variance − known
reconciling items (empty counts as 0). Then, in order:

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Duplicate | Earlier run with the same GL account **and** close period | 🔴 `DUPLICATE_RECONCILIATION` / ✅ `DUPLICATE_CHECK_CLEAR` |
| 2 | Balance | Unexplained difference = 0 (fully agrees, or the reconciling items explain it) | ✅ `BALANCE_MATCH` |
| | | Otherwise | ⚠️ `BALANCE_MISMATCH`, then 🔴 `MATERIAL_VARIANCE` if \|unexplained\| > materiality, else ✅ `WITHIN_MATERIALITY`; ⚠️ `MISSING_RATIONALE` if no rationale |
| 3 | Period | Only when QuickBooks has a books closing date: the period ends after it / on or before it | ⚠️ `PERIOD_NOT_CLOSED` / ✅ `PERIOD_CLOSED` |
| 4 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |
| 5 | Separation | Always: a different controller must approve | ℹ️ `PREPARER_REVIEWER_SEPARATION` |

**Calculations:** GL, subledger, GL − subledger, reconciling items, unexplained difference,
materiality.

**Headline:** duplicate → *Reconciliation already prepared*; any 🔴 → *Material close
variance*; unexplained ≠ 0 → *Immaterial close variance*; any ⚠️ → *Reconciliation needs
evidence*; else *Account reconciled*. **Proposed decision:** any 🔴 → *Reconciliation review
required*; else *Controller sign-off required*. **Approval matrix** routes on the absolute
variance.

**Reviewer checks:** both reports for the period and the proof for each reconciling item.

## Intercompany Matching, Netting & Settlement

Compares what one group company says another owes it with what the other says it owes.

| Field | Meaning | What you can enter |
|---|---|---|
| Sending entity | Company holding the receivable (AR) | Text, e.g. `US Subsidiary` |
| Receiving entity | Company holding the payable (AP) | Text, e.g. `UK Subsidiary` |
| Currency | Currency of the AR | 3 letters |
| Intercompany AR | Amount the sending entity shows | Money, 0 or more |
| Counterparty AP | Amount the receiving entity shows | Money, 0 or more |
| Translation rate | Converts the AP into the AR currency | Number above 0, up to 8 decimals (1 if same currency) |
| Matching tolerance | Largest difference still treated as a match | Money, 0 or more |
| Transfer-pricing/policy notes | Basis of the intercompany charges | Long text, optional |

**How it works:** translated AP = counterparty AP × rate (rounded to cents); difference = AR −
translated AP; amount available to net = the smaller of AR and translated AP. Then, in order:

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Entities | Sending = receiving (ignoring case) | 🔴 `SAME_ENTITY` |
| 2 | Match | Difference against the matching tolerance | ✅ `IC_MATCH` / 🔴 `IC_MISMATCH` |
| 3 | FX | Rate = 1 / any other rate | ✅ `NO_TRANSLATION` / ⚠️ `FX_ASSUMPTION` (confirm source and date) |
| 4 | Transfer pricing | No notes | ⚠️ `TRANSFER_PRICING_REVIEW` |
| 5 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |
| 6 | Settlement | Always | ℹ️ `SETTLEMENT_AUTHORIZATION` |

**Calculations:** AR, AP, rate, translated AP, difference, tolerance, amount available to net.

**Headline:** mismatch → *Intercompany mismatch*; other 🔴 → *Intercompany exception*; any ⚠️ →
*Intercompany match needs review*; else *Intercompany balances match*. **Proposed decision:**
any 🔴 → *Resolve before settlement*; else *Netting proposal for authorization*. **Approval
matrix** routes on the intercompany AR.

**Reviewer checks:** both ledgers, the rate's source and date, and the transfer-pricing basis.

## FP&A Forecast, Variance & Scenario Planning

Compares actual against budget and runs a simple what-if scenario.

| Field | Meaning | What you can enter |
|---|---|---|
| Business unit | Unit being analyzed | Text, e.g. `North America` |
| Forecast period | Period | Text, e.g. `Q4 2026` |
| Actual value | Actual result | Money, can be negative |
| Budget value | Budgeted result | Money, can be negative |
| Scenario volume change (%) | Change in volume | Percent, −100 to 1000 (`5` = 5%) |
| Scenario price change (%) | Change in price | Percent, −100 to 1000 |
| Scenario cost change (%) | Increase in cost, as % of the actual | Percent, −100 to 1000 |
| Planning assumptions | Why these scenario numbers | Long text, optional |

**Prefill from your data:** choose a **business unit** (*Whole company* or a QuickBooks class),
a **forecast period** (month, quarter or year) and a **metric** (*Revenue*, *Operating
profit* or *Operating expenses*). Then:
- **Actual value** = the metric from the monthly profit and loss of that unit, added up over
  the period's months
- **Budget value** = the same metric from the QuickBooks budget (income, cost of goods sold
  and expense accounts; inactive budgets ignored)

Business unit and period are filled in too. Budgets exist only in QuickBooks Plus and
Advanced; without one, the budget stays for you to enter. Scenario % and assumptions stay for
you.

**How it works:**

1. **Variance** = actual − budget; **variance %** = variance ÷ \|budget\| (empty when the
   budget is 0).
2. **Scenario bridge**, each impact rounded to cents and shown separately:

   | Step | Formula | Example (120,000; 5% / 2% / 3%) |
   |---|---|---|
   | Volume impact | actual × volume % | +6,000 |
   | Price impact | (actual + volume impact) × price % | +2,520 |
   | Cost impact | − actual × cost % | −3,600 |
   | Scenario value | actual + the three impacts | 124,920 |

3. **Checks** (in order):

   | Check | Rule | Finding |
   |---|---|---|
   | Materiality | Budget 0 / \|variance %\| > materiality % / otherwise | ⚠️ `NO_BUDGET` / 🔴 `VARIANCE_MATERIAL` / ✅ `VARIANCE_WITHIN_THRESHOLD` |
   | Scenario drivers | Each driver with \|%\| > the scenario review limit | ⚠️ `UNUSUAL_SCENARIO` (one per driver) |
   | Assumptions | Filled in / empty | ℹ️ `ASSUMPTION_APPROVAL` / ⚠️ `MISSING_ASSUMPTIONS` |
   | Budget data | Your data source has P&L figures but no budget at all | ⚠️ `BUDGET_NOT_IN_DATA` |
   | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |
   | Version | Always: the drivers are recorded with the run | ℹ️ `SCENARIO_VERSION` |

**Headline:** any 🔴 → *Budget variance*; any ⚠️ → *Forecast needs review*; else *Within
budget tolerance*. **Proposed decision:** any 🔴 → *Explain the variance and approve the
scenario assumptions*; else *Scenario assumptions for approval*. **Approval matrix** routes on
the absolute variance.

**Reviewer checks:** actual and budget are the approved versions, and the drivers are
documented.

## Treasury Cash Forecasting & Liquidity

Projects cash at the end of a period and spots a shortfall before any money moves.

| Field | Meaning | What you can enter |
|---|---|---|
| Currency | Currency of the forecast | 3 letters, e.g. `USD`, `INR` |
| Opening cash | Cash in the bank today | Money, can be negative (overdraft) |
| Expected inflows | Money expected in (customer receipts) | Money, 0 or more |
| Expected outflows | Money expected out (payroll, suppliers) | Money, 0 or more |
| Minimum liquidity buffer | Cash that must always remain | Money, 0 or more |
| Forecast horizon (days) | How many days ahead | Whole number, 1 to 730 |
| Permitted funding options | Allowed ways to cover a shortfall | Text, optional, e.g. `Revolver draw` |

The entity is the run's legal entity, so it isn't a form field.

**Prefill from your data:** instead of picking one record, enter a **forecast horizon** (days,
default 30) and click *Prefill*. From your data source (QuickBooks or uploads), as of today:

| Field | Comes from |
|---|---|
| Opening cash | the current balance of every **Bank** account |
| Expected inflows | open customer invoices due between today and the end of the horizon (and those with no due date) |
| Expected outflows | open bills due by the end of the horizon, **including overdue ones** (they still have to be paid) |
| Forecast horizon | the value you entered |

Invoices that are **already overdue are not counted** as inflows: collection is uncertain.
Their total is in the snapshot and raised as a warning. The snapshot keeps the parameters, a
summary, and the bank accounts, invoices and bills behind each total (up to 50 of each), so
the reviewer sees exactly what was counted. Currency, buffer and funding options stay for you.

**How it works:** closing cash = opening + inflows − outflows; funding gap = buffer − closing
cash (0 when the buffer holds). Then, in order:

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Negative cash | Closing cash < 0 | 🔴 `NEGATIVE_PROJECTED_CASH` / ✅ `PROJECTED_CASH_POSITIVE` |
| 2 | Buffer | Funding gap > 0 | 🔴 `LIQUIDITY_BUFFER` / ✅ `LIQUIDITY_BUFFER_MET` (with headroom) |
| | | With a gap: gap > dual authorization amount | ⚠️ `DUAL_AUTHORIZATION` |
| | | With a gap: no funding options entered | ⚠️ `NO_FUNDING_OPTIONS` |
| 3 | Overdue receivables | Only with invoices in your data source: open invoices already past due | ⚠️ `OVERDUE_RECEIVABLES` (not counted in prefilled inflows) |
| 4 | Large outflows | Outflows > large outflow limit (off by default) | ⚠️ `LARGE_OUTFLOWS` |
| 5 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |

**Calculations:** opening cash, inflows, outflows, projected closing cash, buffer, funding gap,
horizon.

**Headline:** closing < 0 → *Negative cash projected*; gap → *Liquidity shortfall*; any ⚠️ →
*Liquidity projection needs review*; else *Liquidity within buffer*. **Proposed decision:**
any 🔴 → *Check buffer limits before action*; else *Treasury approver sign-off required*.
**Approval matrix** routes on the funding gap.

**Reviewer checks:** bank balances and the timing of the largest flows.

## Audit Evidence, Controls Testing & SOX

Records the result of testing one control and produces a traceable workpaper.

| Field | Meaning | What you can enter |
|---|---|---|
| Control ID | Control that was tested | Text, e.g. `SOX-AP-003` |
| Control owner | Person responsible for the control | Text, e.g. `AP Controller` |
| Population count | Total items in the period | Whole number, 1 or more |
| Items tested | Items in the sample | Whole number, 1 or more |
| Exceptions found | Tested items that failed | Whole number, 0 or more |
| Evidence references / URLs | Where the evidence is kept | Long text, optional |
| Test procedure / expected control | How it was tested, what the control should do | Long text, optional |

**How it works:** exception rate = exceptions ÷ items tested; coverage = items tested ÷
population (both as %, 2 decimals). Then, in order:

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Sample bounds | Tested > population | 🔴 `SAMPLE_EXCEEDS_POPULATION` |
| | | Exceptions > tested | 🔴 `EXCEPTIONS_EXCEED_SAMPLE` |
| | | Otherwise: tested < minimum sample (or the whole population, if smaller) | ⚠️ `SAMPLE_TOO_SMALL` |
| | | None of the above | ✅ `SAMPLE_WITHIN_BOUNDS` |
| 2 | Exceptions | 0 / above tolerable / within tolerable | ✅ `NO_EXCEPTIONS` / 🔴 `EXCEPTIONS_ABOVE_TOLERABLE` / ⚠️ `EXCEPTIONS_TOLERABLE` |
| 3 | Evidence lineage | Evidence references or a document | ✅ `EVIDENCE_LINEAGE` / ⚠️ `MISSING_EVIDENCE_LINEAGE` |
| 4 | Procedure | No test procedure | ⚠️ `MISSING_TEST_PROCEDURE` |
| 5 | Sign-off | Always: the reviewer concludes | ℹ️ `AUDITOR_SIGN_OFF` |

**Calculations:** population, items tested, exceptions, exception rate, coverage.

**Headline:** exceptions above tolerable → *Control exceptions found*; other 🔴 → *Sample bounds
invalid*; any ⚠️ → *Control test needs completion*; else *Control operating effectively*.
**Proposed decision:** any 🔴 → *Auditor validates impact*; else *SOX reviewer sign-off
required*. No approval amount: always the lowest approval tier.

**Reviewer checks:** the sample was drawn from the full population, and the evidence for
each exception. The reviewer, not the system, decides whether it is a deficiency.

## Financial Reporting, Disclosure & Board Pack

Checks the headline figures for a board pack and drafts a factual summary.

| Field | Meaning | What you can enter |
|---|---|---|
| Report name | Name of the report | Text, e.g. `Q3 Board Pack` |
| Reporting period | Period it covers | Text, up to 20, e.g. `2026-Q3` |
| Reported revenue | Revenue for this period | Money, 0 or more |
| Prior period revenue | Revenue for the previous period | Money, 0 or more |
| Operating profit | Operating profit for this period | Money, can be negative (a loss) |
| Source dataset / approval ID | Where the approved figures come from | Text, optional, but a **high** flag if empty |
| Known disclosures | Disclosures and reporting notes | Long text, optional |

**Prefill from your data:** choose a **reporting period**: a month (`2026-07`), a quarter
(`2026-Q2`) or a year (`2026`). Only periods whose every month is in the data are offered.
From the company's monthly profit and loss:
- **Reported revenue** and **operating profit** = the period's months added up
- **Prior period revenue** = the **same period last year** (2026-Q2 → 2025-Q2), only if all
  its months are in the data
- **Source dataset / approval ID** = where it came from, e.g. *QuickBooks Acme Ltd: P&L
  2026-Q2, data as of 2026-10-21 08:43 UTC*

A figure is left empty rather than added up from part of a period; the snapshot says why.

**How it works:** revenue change = reported − prior; growth % = change ÷ prior (empty if prior
is 0); operating margin % = profit ÷ revenue (empty if revenue is 0). Then, in order:

| # | Check | Rule | Finding |
|---|---|---|---|
| 1 | Source | Source dataset / approval ID filled in | ✅ `SOURCE_REFERENCED` / 🔴 `MISSING_SOURCE_REFERENCE` |
| 2 | Consistency | Operating profit > revenue | 🔴 `PROFIT_EXCEEDS_REVENUE` |
| | | Prior period revenue = 0 | ⚠️ `NO_PRIOR_PERIOD` |
| | | \|growth %\| > revenue change review % | ⚠️ `UNUSUAL_REVENUE_CHANGE` |
| | | None of the above | ✅ `NUMBERS_CONSISTENT` |
| 3 | Period | Only when QuickBooks has a books closing date and the period is a month, quarter or year: it ends after the closing date / on or before it | ⚠️ `PERIOD_NOT_CLOSED` / ✅ `PERIOD_CLOSED` |
| 4 | Disclosures | None recorded | ⚠️ `NO_DISCLOSURES_RECORDED` |
| 5 | Evidence | No document attached | ⚠️ `MISSING_EVIDENCE` |
| 6 | Sign-off | Always | ℹ️ `CFO_SIGN_OFF` |

**Calculations:** reported revenue, prior revenue, "Revenue increased / decreased by", growth
%, operating profit, operating margin %.

**Headline:** no source → *Source references missing*; other 🔴 → *Board figures inconsistent*;
any ⚠️ → *Board pack needs review*; else *Board figures consistent*. **Proposed decision:** any
🔴 → *Resolve source and consistency issues before sign-off*; else *Approve all source claims
and disclosures*. No approval amount: always the lowest approval tier.

**Reviewer checks:** every figure traces to the approved source; the disclosures are complete.

---

## Thresholds the admin can change

Admin Settings → Governance. Each change creates a new version; new analyses use it, older
runs keep the version they were analyzed with. An empty value turns that check off (where
the setting allows it).

| Agent | Setting | Default |
|---|---|---|
| AP Invoice | PO match tolerance | 0.00 |
| | Receipt match tolerance | 0.00 |
| | High-value invoice limit | off |
| Expense Audit | Receipt match tolerance | 0.00 |
| | Policy limits by expense category (e.g. Lodging 200.00) | none |
| | Default policy limit (categories without their own) | off |
| AR Collections | High exposure above | 50,000.00 |
| | Reminder from score | 30 |
| | Escalate from score | 60 |
| Cash Application | Match tolerance | 0.00 |
| | Deduction review threshold | 0.00 (every short payment is reviewed) |
| FP&A | Variance materiality | 10% |
| | Scenario change review limit | 25% |
| Treasury | Dual authorization above | 0.00 (every funding gap) |
| | Large outflow review limit | off |
| SOX Controls | Minimum sample size | 25 |
| | Tolerable exceptions | 0 |
| Board Reporting | Revenue change review threshold | 25% |
| Financial Close, Intercompany | none: materiality / tolerance is entered on each run | |
