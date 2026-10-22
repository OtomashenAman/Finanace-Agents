# The 12 agents at a glance

What each agent does, in one line, with a short example. Every agent works the same way: the
preparer enters (or prefills) the input, the engine runs fixed rules and arithmetic, the AI
writes an explanation, and a Finance Admin approves, requests changes or rejects. No agent posts
entries or moves money.

For fields and exact rules see [agents-user-guide.md](agents-user-guide.md); for test cases
[agents-e2e-testing.md](agents-e2e-testing.md).

| # | Agent | What it does | Example |
|---|---|---|---|
| 01 | **AP Invoice** | Checks a supplier invoice before payment: matches it to the PO and the goods received, catches duplicates, proposes the GL account | Acme bills 12,500 for PO-77 (12,500 received) → PO and receipt match, ready for approval |
| 02 | **Expense Audit** | Checks an employee's card or expense claim against the policy limit, the receipt and earlier claims | 285 hotel claim, Lodging limit 200, the same charge twice → *Duplicate card transaction*, over the limit |
| 03 | **AR Collections** | Ranks an overdue customer by risk and drafts a reminder email for review | Harbor owes 25,000, 45 days late, paid late twice before → priority score 40, draft reminder |
| 04 | **Cash Application** | Matches a customer payment to the open invoice and spots short payments (deductions) | 900 received for invoice INV-8021 of 1,000 → *Short payment* of 100, deduction to classify |
| 05 | **Financial Close** | Reconciles a GL account to its subledger at month end and explains the difference | A/R in the GL 120,000 vs aging report 119,000, materiality 500 → *Material close variance* |
| 06 | **Intercompany** | Compares what two group companies owe each other and proposes netting | US sub shows 50,000 receivable, UK sub 49,000 payable → 1,000 mismatch to resolve |
| 07 | **FP&A** | Compares actual with budget and runs a what-if scenario (volume, price, cost) | Revenue 120,000 vs budget 100,000 → 20% variance; scenario +5% volume, +2% price, +3% cost → 124,920 |
| 08 | **Treasury** | Projects cash at the end of a horizon and flags a shortfall below the minimum buffer | Opening 250,000 + inflows 150,000 − outflows 300,000 = 100,000, buffer 125,000 → 25,000 gap |
| 09 | **Revenue Recognition** | Abstracts a customer contract (ASC 606 / IFRS 15) and shows a straight-line revenue illustration | 120,000 contract over 12 months for hosting and support → 10,000/month, two obligations to allocate |
| 10 | **Lease Accounting** | Abstracts a lease and computes the indicative lease liability and right-of-use asset | Rent 5,000/month for 24 months at 6% → liability 112,814.33, interest 7,185.67 |
| 11 | **SOX Controls** | Records a control test: sample size, exceptions and evidence, as an audit workpaper | 25 of 100 items tested, 2 failed → 8% exception rate, *Control exceptions found* |
| 12 | **Board Reporting** | Checks the figures for a board pack and drafts commentary from approved numbers | Q3 revenue 1,000,000 vs 900,000 last year → +11.11%, margin 15%, source reference needed |

## Where the input comes from

| Input | Agents |
|---|---|
| Pick one record from QuickBooks or an upload | AP Invoice (bill), Expense Audit (expense), AR Collections (customer), Cash Application (payment), Revenue Recognition (customer invoice), Lease Accounting (rent bill) |
| Enter parameters, the agent adds up the data | Treasury (horizon), Financial Close (account + month), FP&A (unit + period + metric), Board Reporting (period) |
| Typed in by hand only | Intercompany, SOX Controls |

## How each agent works

Each agent first calculates, then runs its checks in a fixed order. A check gives *high* (an
exception: the run gets High priority), *warning* (needs review), *pass* or *info*. Limits
marked *(Governance)* can be changed by the Finance Admin. Every agent also warns when no
supporting document is attached.

### 01 AP Invoice

- **Logic:** invoice − PO amount and invoice − received amount, each against its tolerance
  *(Governance, default 0)*.
- **Checks:** same supplier + invoice number analyzed before (high) · supplier inactive in the
  vendor master (high) · PO or receipt mismatch (high) · tax more than the total (high) · no GL account (warning).
- **Example:** invoice 12,500, PO 12,500, received 10,000 → invoice − PO = 0 (pass), invoice −
  received = 2,500 (high) → *Invoice discrepancy*.

### 02 Expense Audit

- **Logic:** amount over the limit = claim − policy limit (the category's limit from
  Governance, e.g. Lodging 200); claim − receipt total against the receipt tolerance.
- **Checks:** card transaction already claimed, or charged twice (same merchant, amount and
  date) (high) · no receipt (high) · over the limit (high) · claim ≠ receipt total (high).
- **Example:** claim 285, Lodging limit 200, receipt 285 → 85 over the limit (high), receipt
  reconciles (pass) → *Policy exception*.

### 03 AR Collections

- **Logic:** priority score 0–100 = days-overdue points (1–30: 10, 31–60: 30, 61–90: 50,
  90+: 70) + 10 if the balance is above 50,000 + 5 per earlier late payment (at most 20).
  Score ≥ 60 → escalate, ≥ 30 → send reminder, below → monitor; an open dispute always holds.
- **Checks:** overdue (warning) (over 90 days (high)) · open dispute (high) · high exposure (warning) · strategic
  account (warning). The AI drafts the reminder email; nothing is sent.
- **Example:** 25,000 open, 45 days late, 2 late payments → 30 + 0 + 10 = **40** → *Send
  reminder*.

### 04 Cash Application

- **Logic:** short payment = invoice open amount − payment (negative = overpaid).
- **Checks:** same payment reference applied before (high) · reference not verified (warning) · invoice
  belongs to another customer (high) · short payment (warning) and, above the deduction threshold
  *(Governance, default 0)*, deduction review (high) · difference with no remittance advice (warning).
- **Example:** payment 900 for INV-8021 open 1,000 → short **100** → *Short payment*,
  deduction to classify (high).

### 05 Financial Close

- **Logic:** variance = GL balance − subledger balance; unexplained = variance − known
  reconciling items.
- **Checks:** same account + period reconciled before (high) · unexplained ≠ 0 (warning), and above
  materiality (high) · no rationale for an adjustment (warning) · period not closed in QuickBooks (warning).
  A different controller must approve.
- **Example:** GL 120,000, subledger 119,000, no reconciling items, materiality 500 →
  unexplained **1,000** > 500 → *Material close variance* (high).

### 06 Intercompany

- **Logic:** translated AP = counterparty AP × rate; difference = AR − translated AP; amount
  to net = the smaller of the two.
- **Checks:** sending = receiving entity (high) · difference above the tolerance (high) · a rate other
  than 1 (warning) (confirm source and date) · no transfer-pricing notes (warning).
- **Example:** US sub AR 50,000, UK sub AP 49,000, rate 1, tolerance 100 → difference
  **1,000** (high) → *Intercompany mismatch*; 49,000 can be netted.

### 07 FP&A

- **Logic:** variance = actual − budget; variance % = variance ÷ budget. Scenario = actual +
  volume impact (actual × volume %) + price impact ((actual + volume impact) × price %) − cost
  impact (actual × cost %).
- **Checks:** variance % above materiality *(Governance, default 10%)* (high) · a driver above
  the scenario limit *(default 25%)* (warning) · no assumptions (warning) · no budget in the data (warning).
- **Example:** actual 120,000, budget 100,000 → variance 20,000 = **20%** (high). Scenario +5% /
  +2% / +3%: +6,000 + 2,520 − 3,600 → **124,920**.

### 08 Treasury

- **Logic:** closing cash = opening + inflows − outflows; funding gap = buffer − closing
  (0 if covered). Prefill: bank balances, invoices and bills due within the horizon (already
  overdue invoices are not counted).
- **Checks:** closing cash below 0 (high) · below the buffer (high), then dual authorization (warning) and
  no funding options (warning) · overdue receivables (warning) · large outflows (warning).
- **Example:** 250,000 + 150,000 − 300,000 = **100,000**; buffer 125,000 → gap **25,000** →
  *Liquidity shortfall*.

### 09 Revenue Recognition

- **Logic:** obligations = the listed items (split on lines, `;`, `,`, `and`); monthly revenue
  = contract total ÷ term (the last month takes the rounding).
- **Checks:** more than one obligation (high) (allocate the price by standalone selling price) ·
  variable consideration (warning) · contract change (warning) · total above the policy review limit
  *(Governance, default 100,000)* (warning) · invoice of another customer (high).
- **Example:** 120,000 over 12 months, "Hosting and support" → **10,000/month**, 2
  obligations (high) → *Allocation across obligations needed*.

### 10 Lease Accounting

- **Logic:** monthly rate = annual rate ÷ 12; lease liability = present value of the remaining
  payments (paid at month end); right-of-use asset = liability + initial direct costs;
  interest = total payments − liability.
- **Checks:** rate 0% (high) · rate outside 1–15% *(Governance)* (warning) · renewal/termination options,
  or none recorded (warning) · same lessor + asset analyzed before (modification) (warning) · payment ≠
  latest rent bill (warning) · 12 months or less: short-term exemption (info).
- **Example:** 5,000 × 24 months at 6% (0.5% a month) → liability **112,814.33**, payments
  120,000, interest **7,185.67** → *Lease schedule*.

### 11 SOX Controls

- **Logic:** exception rate = exceptions ÷ items tested; coverage = items tested ÷
  population.
- **Checks:** tested > population, or exceptions > tested (high) · sample below the minimum
  *(Governance, default 25)* (warning) · exceptions above the tolerable count *(default 0)* (high),
  within it (warning) · no evidence references (warning) · no test procedure (warning).
- **Example:** population 100, tested 25, 2 exceptions → rate **8%**, coverage 25%, 2 > 0
  tolerable (high) → *Control exceptions found*.

### 12 Board Reporting

- **Logic:** revenue change = reported − prior (same period last year); growth % = change ÷
  prior; operating margin % = profit ÷ revenue.
- **Checks:** no source dataset / approval ID (high) · profit more than revenue (high) · growth above
  the review limit *(Governance, default 25%)* (warning) · no prior period (warning) · no disclosures (warning) ·
  period not closed (warning). The CFO signs off.
- **Example:** 1,000,000 vs 900,000 → +100,000 = **11.11%**, profit 150,000 → margin
  **15%**; no source ID (high) → *Source references missing*.
