# Service POD (Phase 1: foundation)

The five workflows of `Finance and Accounting AI agentsV1.1` (AR Collections, Bank-to-Invoice
Reconciliation, FP&A Trends, Treasury Forecast, Financial Reporting) run in the **Service POD**
section, next to the 12 agents. Phase 1 is the shared foundation; each workflow's own screens
and calculations come in phases 2 to 4.

Ground rules (deck slide 44):

- **QuickBooks is read only.** The module works on immutable snapshots. Anything to book becomes
  a manual posting task: a Finance Admin posts in QuickBooks, records the transaction ID, and a
  fresh snapshot that contains it verifies the task.
- **Nothing missing is invented.** A collection the source doesn't supply stays absent; workflows
  that need it refuse the snapshot.
- **Maker-checker everywhere.** Reviewers act only on cases they didn't prepare; the CFO (final
  approver) must be a different person from the reviewer. Approvals bind a fingerprint of the
  case's content: any change after a review sends it back to review.
- **Promises are not receipts.** A customer commitment changes no balance.

## Roles

Admin Settings → Service POD assigns per workflow:

| Capacity | Does | Deck role |
|---|---|---|
| preparer | opens cases, drafts messages, imports replies, proposes postings | AR user, Cash Analyst, FP&A Analyst, Treasury Analyst, Reporting Analyst |
| reviewer | approves messages, documents, commitments, results | AR Reviewer, Cash Reviewer, Finance Head, Treasury Head, Controller |
| final_approver | independent final sign-off (Treasury, Reporting) | CFO |
| poster | imports sources, approves / records / verifies manual postings | Finance Admin |

Legal entity access comes from the Users tab. The Finance Admin *role* can read everything
for oversight but decides nothing without a capacity.

## Source snapshots

Import on Service POD → Sources (posters only):

1. **Normalized export (JSON)**: the contract below. Sample:
   [`sample-uploads/service-pod/demo-snapshot.json`](sample-uploads/service-pod/demo-snapshot.json)
   (fictional, `SYNTHETIC_DEMO`).
2. **QuickBooks Online**: freezes your synced connection's customers, invoices, payments and
   accounts. A sandbox company is labelled demo.
3. **Bank statement (CSV)** on an existing snapshot: makes a *new* snapshot with the receipts
   added. Columns `reference,payer,date,amount,currency,cleared[,proof_reference]`. Sample:
   [`sample-uploads/service-pod/bank-statement.csv`](sample-uploads/service-pod/bank-statement.csv).

The same content imported twice returns the existing snapshot (canonical JSON SHA-256). A
database trigger refuses any UPDATE or DELETE of a snapshot.

### Export contract

Top level (all required): `provenance` (`QUICKBOOKS_READONLY_EXPORT` | `SYNTHETIC_DEMO`),
`company_id`, `company_name`, `entity` (= the legal entity code it is imported into),
`currency` (3 letters), `basis` (`Accrual` | `Cash`), `as_of`, `source_reference`.

Collections (each optional; amounts as decimal strings):

| Collection | Fields |
|---|---|
| customers | id, name, email (the verified contact), contact_name |
| invoices | id, number, customer_id, txn_date, due_date, original_amount, balance, terms, document_ref |
| payments | id, customer_id, date, amount, currency, reference, allocations[{invoice_id, amount}] |
| accounts | id, name, number, classification (Income, CostOfGoodsSold, Expense, OtherIncome, OtherExpense, Asset, Liability, Equity) |
| gl_lines | id, account_id, period (YYYY-MM), amount, report_id, transaction_ids[] |
| transactions | id, date, period, type, counterparty, account_id, amount (net, signed), tax, status (Posted/Draft/Voided), gl_line_id, document_ref, entity |
| bank_receipts | reference, payer, date, amount, currency, cleared, proof_reference |
| contracts | id, customer_id, invoice_ids[], terms, status |
| planned_outflows | id, date, amount, category, approved, approval_ref |
| cash_position (object) | as_of, bank_balance, quickbooks_cash_balance, reconciliation_balance, policy_buffer, cleared, proof_reference |
| balance_sheets | period, assets, liabilities, equity, report_id |
| close_status | period, status (Open/Closed), required_checks[] |

Checked on import: unique IDs, every reference resolves (invoice → customer, allocation →
invoice, GL line → account), transactions and GL lines cite each other with the same account
and period, a transaction's date falls in its period and its entity matches, allocations don't
exceed the payment, an invoice balance lies between 0 and its amount.

What each workflow needs before a case can open:

| Workflow | Required collections |
|---|---|
| AR Collections | customers, invoices |
| Bank-to-Invoice | customers, invoices, payments, bank_receipts |
| FP&A Trends | accounts, gl_lines, transactions |
| Treasury | cash_position, invoices, planned_outflows |
| Reporting | accounts, gl_lines, transactions, balance_sheets, close_status, invoices |

## Cases

Every change is `POST /api/v1/pod/cases/{id}/actions` with the version the screen last saw
(409 `stale_version` if someone changed it since). The case detail returns, per action,
`null` (you may do it now) or the reason you can't.

Status: draft → in_review → (awaiting_final →) approved → completed; or changes_requested /
rejected / cancelled. Completed, rejected and cancelled cases are locked.

- **Review tasks** (unknown date, dispute, missing document, ambiguity, scope): open blocking
  ones stop submission and approval.
- **Commitments**: invoice, amount (never more than the open balance in total), date (required
  to approve), probability (a reason below 1), the customer's words.
- **Owned actions**: title, owner, due date, outcome.
- A case completes only when its posting tasks are verified and no send is unresolved.

## Email

`EMAIL_PROVIDER=outbox` (default) records approved messages and sends nothing; they show as
*Simulated*. `brevo` sends through Brevo (`BREVO_API_KEY`, verified `EMAIL_SENDER`).

- The preparer drafts; a reviewer who isn't the author approves the exact message (subject,
  body, recipient, attachments, purpose, transport). Any edit withdraws the approval.
- Customer mail goes only to the customer's verified contact in the snapshot (demo snapshots
  excepted); internal mail only to `POD_INTERNAL_RECIPIENTS`.
- Send is separate and happens once. A timeout becomes *outcome unknown*: a reviewer checks
  the provider log and reconciles it; it is never retried automatically.
- Replies: upload the `.eml` (its In-Reply-To / References prove the thread) or paste the text
  and pick the message it answers. The sender must be the address the message went to; the same
  Message-ID with different content is refused.
- Attachments: documents of the case, approved by someone other than the uploader.

## AI

`src/app/service_pod/ai.py`: `extract()` returns structured output only if the workflow's
validator accepts it (otherwise the action stops, no fallback), with provider / model / prompt
version provenance. `cited_narrative()` lets the model reference deterministic facts by ID and
rejects any digit, currency or percent sign in its prose. Used from phase 2 on.

## Security added in Phase 1

- Session cookies are `SameSite=Strict`.
- POST/PUT/PATCH/DELETE from another origin than `PUBLIC_BASE_URL` (or `CORS_ORIGINS`) get 403;
  any localhost port is allowed outside production.
