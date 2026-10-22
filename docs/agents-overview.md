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
