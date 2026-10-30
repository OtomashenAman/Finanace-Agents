# Service POD

The five workflows of `Finance and Accounting AI agentsV1.1` (AR Collections, Bank-to-Invoice
Reconciliation, FP&A Trends, Treasury Forecast, Financial Reporting) run in the **Service POD**
section, next to the 12 agents. Phase 1 built the shared foundation; phase 2 the AR
Collections and Bank-to-Invoice workflows. FP&A, Reporting and Treasury follow.

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
3. **QuickBooks Desktop / Enterprise (qbXML)**: one file with the Company, Customer, Invoice,
   ReceivePayment and Account query responses; you state currency, basis and as-of date. Every
   response must have completed (status OK, no iterator rows left). Sample:
   [`sample-uploads/service-pod/qbxml-export.xml`](sample-uploads/service-pod/qbxml-export.xml).
4. **Bank statement (CSV)** on an existing snapshot: makes a *new* snapshot with the receipts
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

## AR Collections

Service POD → **AR Portfolio**: AR balance, overdue > 30 days (a priority, not a limit: any
overdue invoice can be collected), approved promises, open exceptions, aging and the next
action per customer. **Open case** takes the customer's overdue invoices.

1. **Suggest draft** (purpose *Ask for amounts and payment dates*): the invoice table comes
   from the source; the AI writes only the opening and closing and may not write a figure
   (if it does, or there's no AI, a labelled template is used). The table must stay in the
   body unchanged, and is checked again against the source at approval.
2. A reviewer approves after ticking recipient, invoice mapping and tone; then send.
3. Import the reply. The AI reads it into tranches (invoice, amount, date or none, the
   customer's exact words), disputes and document requests. Checks: every quote is in the
   reply and every invoice is the case's (else the whole reading is refused and a person
   reads it); per promise, the amount is in the customer's words (or is the full balance for
   "both"), the date is in their words ("now" isn't a date), confidence ≥ 0.8, no conditions,
   and promises + disputes stay within the open balance. What passes becomes a *proposed*
   commitment; everything else becomes a review task.
4. A missing date settles only from a later reply that states it; a document request only
   when an approved document of that kind for that invoice is added.
5. Approval needs every commitment decided, nothing open or disputed, and current balances
   (a newer source blocks it until **refresh source**).

## Bank-to-Invoice

Service POD → **Unapplied Cash**: receipts not yet recorded in QuickBooks, the matched payer,
possible duplicates and pending admin work. A case opens only on a cleared receipt, once per
receipt, with a payer that matches the customer (or the preparer's evidence that it does).

1. Ask the customer which invoices the payment covers (fact block: the receipt and the open
   invoices). A matching amount never decides the allocation.
2. The reply is read into allocation lines in the customer's words; they must add up to the
   receipt exactly, each within its invoice's open balance. The preparer can also record it by
   hand from the reply (the quote and amounts are checked).
3. After approval, **Queue manual QuickBooks posting** creates the Receive Payment task with
   the expected balances after posting.
4. The Finance Admin posts in QuickBooks, records the transaction ID and verifies with a fresh
   export: one payment with the bank reference, same date, customer, amount and currency,
   applied exactly as approved, and each invoice's remaining balance as expected.
5. Only then can the acknowledgement go to the customer.

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
rejects any digit, currency or percent sign in its prose. Replies are read in the background
(`pod.extract_reply` job); without a working AI nothing is guessed and a person gets a review
task to read the reply.

## Security added in Phase 1

- Session cookies are `SameSite=Strict`.
- POST/PUT/PATCH/DELETE from another origin than `PUBLIC_BASE_URL` (or `CORS_ORIGINS`) get 403;
  any localhost port is allowed outside production.

## Code layout and adding a workflow

```
src/app/service_pod/
  core/        the engine, workflow-independent: workflows.py (keys, roles, spec), hooks.py
               (what a workflow can plug in), registry.py, access/, snapshots/ (importers/
               one module per source), cases/, messaging/, tasks/
  common/      helpers the workflows share: ai, reading (customer's words), drafting,
               matching, selection, worklists, canonical, people
  flows/       one package per workflow: spec.py, schemas.py, prompt.py, service.py,
               reading.py, views.py, router.py (+ actions.py, verification.py when needed)
src/frontend/src/features/service-pod/
  flows/       one folder per workflow (case panel, pages) and the FLOW_UI registry
```

To add a workflow (FP&A, Treasury and Reporting already have their key and spec):

1. Backend: in `flows/<key>/` write the rules (`service.py`, `reading.py`...) and register
   them in its `__init__.py`: `register(SPEC, WorkflowHooks(...), router)`.
2. A brand-new workflow also needs a `WorkflowKey` value, `flows/<key>/spec.py`, an import in
   `flows/__init__.py` and a migration (the key is in database check constraints).
3. Frontend: `features/service-pod/flows/<workflow>/` with its case panel and `FlowUi`, added
   to `flows/index.ts`; its pages in `App.tsx` and the POD tabs.

The engine (`core/`) doesn't change. `tests/service_pod/test_structure.py` checks every
workflow is registered and the worker knows every background job.

