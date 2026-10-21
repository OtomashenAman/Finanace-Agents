# Agents: user guide

How a run works in the 10 agents that have a workspace: the 3 steps every run goes through,
then each agent's input fields, what they mean and what you can enter. (Revenue Recognition
and Lease Accounting don't have a workspace yet.)

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

**Prefill:** with QuickBooks connected (or a bills file uploaded), *Prefill from your data*
fills the form from a bill.

**Result:**
- The 3-way match: invoice vs PO, invoice vs received
- Duplicate check: same supplier and invoice number in an earlier run
- Vendor master check: is the supplier an active vendor
- Tax not above the total
- Missing GL account or evidence

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

**Result:**
- Amount over the policy limit; claim − receipt total
- Flags: no receipt, over the limit, claim doesn't match the receipt, card transaction already
  claimed (in the prior IDs or in an earlier run)
- **Draft for review:** a clarification request to the employee

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

**Priority score (0–100)**, calculated by fixed rules:

| Part | Points |
|---|---|
| Days overdue: 0 / 1–30 / 31–60 / 61–90 / 90+ | 0 / 10 / 30 / 50 / 70 |
| Open balance above the high exposure level (admin setting, default 50,000) | +10 |
| Each previous late payment | +5 (at most +20) |

**Next action:** an open dispute always means **Hold – resolve dispute**. Otherwise a score of
60+ is **Escalate**, 30–59 **Send reminder**, below 30 **Monitor** (the 30 and 60 are admin
settings).

**Result:** aging bucket, score, next action; flags for aging, high exposure, dispute block,
strategic account and promise to pay. **Draft for review:** a payment reminder email, or an
internal note when there is a dispute.

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

**Result:**
- Invoice open − payment: positive = short payment, negative = overpayment
- Flags: reference not verified, short payment, deduction above the review threshold (must
  be classified), overpayment, no remittance advice for a difference, payment reference
  already used in an earlier run

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

**Result:**
- Variance = GL balance − subledger balance
- Unexplained difference = variance − known reconciling items
- High flag if the unexplained difference is above materiality
- Duplicate check: same account and period

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

**Result:**
- Translated AP = counterparty AP × rate; difference = AR − translated AP
- Amount available to net = the smaller of the two
- Flags: mismatch above tolerance, FX rate to confirm (rate ≠ 1), no transfer-pricing notes,
  same entity on both sides; settlement always needs authorization

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

**Scenario bridge** (each impact shown separately):

| Step | Formula | Example (120,000; 5% / 2% / 3%) |
|---|---|---|
| Volume impact | actual × volume % | +6,000 |
| Price impact | (actual + volume impact) × price % | +2,520 |
| Cost impact | − actual × cost % | −3,600 |
| Scenario value | actual + the three impacts | 124,920 |

**Result:** variance and variance %; flags when the variance is above the materiality %
(admin setting, default 10%), a scenario driver is unusually large (default 25%), or no
assumptions were given.

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

**Result:**
- Closing cash = opening cash + inflows − outflows
- Funding gap = how far closing cash falls below the buffer
- Flags: negative cash, buffer breached, dual authorization needed, no funding options

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

**Result:**
- Exception rate = exceptions ÷ items tested
- Coverage = items tested ÷ population
- Flags: sample larger than the population, sample too small, more exceptions than
  tolerable, evidence missing

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

**Result:**
- Revenue change, growth % and operating margin %
- Flags: missing source, profit above revenue, unusually large revenue change (threshold set
  by the admin)

**Reviewer checks:** every figure traces to the approved source; the disclosures are complete.

---

## Thresholds the admin can change

Admin Settings → Governance. Each change creates a new version; new analyses use it, older
runs keep the version they were analyzed with.

| Agent | Thresholds |
|---|---|
| AP Invoice | PO match tolerance, receipt match tolerance, high-value invoice limit |
| Expense Audit | Receipt match tolerance |
| AR Collections | High exposure above, reminder from score, escalate from score |
| Cash Application | Match tolerance, deduction review threshold |
| FP&A | Variance materiality (%), scenario change review limit (%) |
| Treasury | Dual authorization above, large outflow review limit |
| Board Reporting | Revenue change review threshold (%) |
| SOX Controls | Minimum sample size, tolerable exceptions |
| Financial Close, Intercompany | None (materiality / tolerance is entered on each run) |
