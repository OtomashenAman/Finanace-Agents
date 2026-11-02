# Finance Agent Command Center (FinanceACC)

12 AI finance agents with deterministic rule engines, guarded LLM narratives,
maker-checker approvals and an immutable audit trail.

| Layer | Stack |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, Azure OpenAI (pluggable LLM layer), `uv` |
| Database | PostgreSQL 16 + pgvector (same image locally, in CI and in prod) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui |
| Runtime | Docker multi-stage images, nginx (prod), GitHub Actions CI |

---

## Prerequisites (Linux, macOS, Windows)

| Tool | Version | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 0.13+ | manages Python 3.12 itself, no system Python needed |
| [Node.js](https://nodejs.org/) | 22 (see `src/frontend/.nvmrc`) | or `nvm use` / `fnm use` inside `src/frontend` |
| [Docker](https://docs.docker.com/get-docker/) | Docker Desktop / Engine with Compose v2 | for Postgres and the full stack |

`make` is **not** required. All tasks run through [Poe the Poet](https://poethepoet.natn.io/)
(`uv run poe <task>`), defined once in `pyproject.toml`, and behave the same on every OS.
On Linux/macOS, `make <task>` is an optional shortcut for the same thing.

## Fresh clone → running app

```bash
git clone <repo-url> && cd FinanceACC
uv run poe setup        # .env from .env.example, Python + npm deps
uv run poe db-up        # Postgres/pgvector on localhost:5434 + migrations
uv run poe seed         # demo Finance Admin from DEMO_ADMIN_* in .env
uv run poe dev-backend  # terminal 1 → http://localhost:8088/docs
uv run poe dev-frontend # terminal 2 → http://localhost:8081
```

Or run everything in Docker instead (db + backend reload + Vite HMR):
```bash
uv run poe docker-up
```
- Frontend: http://localhost:8081 (`/api/*` is proxied to the backend)
- Backend:  http://localhost:8088 (docs at `/docs`)
- Postgres: localhost:5434 (user/password/db: `finance` / `finance` / `finance_acc`)

> **Docker Desktop (Windows, macOS and Linux):** its VM file sharing can drop file-change events, so hot reload
> may serve stale files. Set `DOCKER_FILE_POLLING=true` in `.env` and run `docker compose up -d` to recreate the containers.

### Signing in
Set `DEMO_ADMIN_PASSWORD` in `.env`, run `uv run poe seed`, then sign in at http://localhost:8081
as `finance.admin@example.com`. Locked out after 5 wrong attempts? `uv run poe seed --reset-password`.

Auth model: argon2id password hashes, short-lived JWT access token + rotating refresh token, both
in `HttpOnly` `SameSite=Lax` cookies (set `COOKIE_SECURE=true` behind HTTPS). Refresh-token reuse
revokes the whole login, failed logins lock the account, and every auth event is written to
`audit_events`. API: `POST /api/v1/auth/login|refresh|logout`, `GET /api/v1/auth/me`.

### Agent catalog
Each agent is one class in `src/app/agent_catalog/agents/<agent>.py`, registered in
`src/app/agent_catalog/registry.py` (`AGENTS`). `uv run poe sync-agents` upserts the registry into
the `agents` table (it also runs in `poe db-up` and in the production `migrate` service).

To add an agent: create the file, add the class to `AGENTS`, run `uv run poe sync-agents`. The
catalog and the overview's *Active Agents* KPI pick it up automatically. A test fails if an agent
file is not registered. Code owns names/descriptions; admins own `is_active` (toggle on the catalog
card) and `agent_assignments` (which user may prepare/review which agent). Agents removed from the
registry are retired, never deleted.

### Agent workspace (Input → Result → Review)
Implemented for **AP Invoice** so far; other agents show "workspace coming soon" until their
folder gets an `input_schema`, `run_model` and `analyze()` (see `agents/ap_invoice/`).

- Roles: **Finance Admin** runs every agent, sees and approves every user's runs (own runs
  included, audited as `self_review`) and manages users under Admin Settings (`/admin/users`,
  API `/api/v1/users`). A **User** only runs the agents an admin assigns, on their own data, and
  only ever sees their own runs; users never approve.
- Data sources (`/data-sources`, API `/api/v1/data-sources`): every user connects **their own**
  QuickBooks company or uploads CSV/XLSX (vendors, bills, purchase orders, chart of accounts).
  Records are normalized into `finance_records`, private to their owner; agents read them through
  `AnalysisContext.data` (e.g. AP Invoice checks the vendor master) and runs can be prefilled
  from a record (`PUT .../runs/{id}/source`), freezing a snapshot the reviewer sees.
  - Each user connects with **their own Intuit app** (Client ID/Secret entered on Connect) and
    registers the Redirect URI shown there (`PUBLIC_BASE_URL` +
    `/api/v1/data-sources/quickbooks/callback`). Nothing about a connection is shared.
  - OAuth tokens and client secrets are encrypted with `DATA_ENCRYPTION_KEY` (required in
    production). The OAuth `state` is signed, expires in 15 minutes and is single use.
  - Intuit remembers its sign-in in the browser: to connect a different QuickBooks login, sign
    out of Intuit first or use a private window.
- Approvals (`/approvals`, API `/api/v1/approvals`): the admin's queue of submitted runs across
  agents (plus recent decisions); users see their own runs still waiting.
- Audit Trail (`/audit`, API `/api/v1/audit-events`): read-only, newest first with keyset
  pagination and filters. Admins see every event and can export CSV (itself audited); users see
  their own actions, changes to their account and events on their own runs, without other
  people's IP or browser. Each run also shows its own timeline (`.../runs/{id}/timeline`).
- AI monitoring (Admin Settings → AI monitoring, API `/api/v1/admin/ai-monitoring?days=7`):
  every explanation call from `run_narratives`, i.e. volume, failure rate, p95 latency, tokens,
  guard notes, per day, model and agent, plus recent failures. The overview's "Model execution"
  line shows the 7-day figures.
- Legal entities (Admin Settings → Legal entities, API `/api/v1/entities`): every run is filed
  for one entity (`agent_runs.entity_id`, common to all agents). Admins assign entities to users
  (`PUT /api/v1/users/{id}/entities`); users only start and see runs of their entities, admins
  work across all. Scoping switches on with the first entity; with one entity it's picked
  automatically. Overview, approvals and run history filter by entity.
- Governance (Admin Settings → Governance, API `/api/v1/admin/governance/...`):
  - Maker-checker: "Allow Finance Admins to approve their own runs" (on by default). Off, nobody
    approves a run they prepared.
  - Thresholds: an agent's `policy_schema` (AP Invoice: PO/receipt tolerance, high-value limit).
    Saving makes a new version (`ap_invoice/v2`...); runs record `policy_version` and
    `policy_values` from analysis, and both are part of the result hash.
  - Approval matrix: amount tiers per agent (`approval_amount()`, e.g. invoice total) with 1–3
    approvals and optional named approvers; fixed on the run at submit (`required_approvals`,
    `approval_rule`). Each approval must come from a different admin; a resubmit starts over.
- My Worklist (`/worklist`, API `/api/v1/worklist`): what needs the viewer now (approvals with
  the review SLA, changes requested, validation failures, runs to submit, stale drafts, broken
  data sources, and for admins locked accounts), what waits on others, and for admins users'
  connection problems. The sidebar shows the count.
- Overview filters: period, legal entity, agent and priority.
- Background jobs: a Postgres queue (`jobs`, claimed with `FOR UPDATE SKIP LOCKED`) run by the
  `worker` service (`python -m src.app.cli.worker`). Jobs are idempotent (`dedupe_key`), retried
  with backoff and marked failed after their last attempt; admins see and retry them under
  Admin Settings → Monitoring. The AI explanation is drafted this way (the run shows
  `narrative_pending` until it's ready; submitting waits for it). `JOBS_MODE=inline` runs jobs
  inside the request instead (tests). `POST .../runs` accepts an `Idempotency-Key` header.
- Delegated approvers (Governance): an admin lets another approve in their place for a period;
  reviews record `on_behalf_of`, and one person never counts twice in a multi-approval round.
- Evidence pack: `GET .../runs/{id}/evidence-pack` is a ZIP with the run, documents' text, the
  data source snapshot, the audit timeline and a SHA-256 manifest (the export is audited).
- QuickBooks write-back: after approval the preparer can note the approval on the QuickBooks
  bill the run came from (`POST .../runs/{id}/write-back`, a background job; only the bill's
  private note changes). For an invoice entered by hand (or from a PDF/upload), the preparer
  picks one of their QuickBooks companies and an expense account and the bill is created there
  (vendor matched by name from the last sync; if the vendor already has a bill with that
  number, it is used instead of creating a second). The receipt is kept on the run
  (`run_actions`).
- Audit integrity: database triggers make `audit_events` append-only and chain every event to
  the previous one by SHA-256. `python -m src.app.cli.audit verify` (or Audit Trail as an admin)
  recomputes the chain; `... audit purge` removes events past `AUDIT_RETENTION_DAYS` and records
  the purge.
- Observability: `X-Request-ID` on every response and log line, `LOG_FORMAT=json` for log
  shippers, `/ready` (database) next to `/health`, and `/metrics` for Prometheus (HTTP counters
  plus queue, AI, approval, account and data source gauges; `METRICS_TOKEN`). With several
  server processes set `METRICS_DIR` to a shared tmpfs directory (as in
  `docker-compose.prod.yml`): each process keeps its counters there and every scrape sums
  them. Example scrape
  config and alert rules: `ops/prometheus/`.
- Header search (`GET /api/v1/search`, Ctrl/⌘ K): runs by number, headline or invoice number,
  agents, pages and, for admins, people and legal entities, scoped like the rest of the app.
  Help (`/help`) explains each role's tasks; My account (`/account`) changes the password;
  "Forgot password?" on the sign-in page puts a reset request in the admins' worklist.
- Sessions are per browser tab: the SPA sends its tab's id in `X-Session-Slot` and the httpOnly
  auth cookies are named after it, so an admin and a user can be signed in side by side. A new
  tab opens with the last account used; the user menu's "another account" icon signs in a
  different one in that tab only.
- Finance POD (`/finance`, API `/api/v1/finance/...`, `src/app/finance_pod/`): the GIA AP / AR
  agents on the Service POD's case engine, in their own tab. Multi-user: a Finance Admin grants
  capacities (Admin Settings → Finance POD: requester, budget owner, buyer, controller, ...),
  per legal entity or for all. Each workflow declares the requirement's L4 tasks and L5 steps
  (`service_pod/core/steps/`): every L5 exists as a row from the moment a case opens, steps go
  in order, a person's step needs its capacity, `distinct_from` enforces segregation of duties
  (for admins too), an agent step runs its handler, a step that doesn't apply is recorded as
  not applicable with its reason, and the case can't be approved while any step is open.
  `finance_pod/requirements/` holds the requirement as data; `test_requirement_coverage.py`
  fails when a built phase misses any L4/L5 step, checkpoint, rule (each needs a test marked
  `@pytest.mark.requirement("AP1.R1")`) or measure. The two PODs never serve each other's cases.
- Finance POD AP-1 (Purchase Request & PO, `finance_pod/flows/ap_purchase_request`; Vendor
  Onboarding, `.../ap_vendor_onboarding`), every To-Be L4/L5 step of GIA pages 3-4:
  - Request: the requester describes the need (catalogue items; a quote if any). The request agent
    codes it (from the requester or earlier orders; a grant is never assumed), prices it
    (contract, then catalogue, then estimate), and fails while the cost centre or lab is missing.
    A past "needed by" date raises a blocking review task.
  - Budget: the budget agent computes budget − GL actual − committed (open POs and requests, and
    released requests not yet in ERPNext) per department and grant, checks the grant's period,
    status and allowed item groups, and routes by the authority matrix. The budget owner
    approves, rejects (case cancelled) or queries (sent back to the requester, counted as rework).
  - Sourcing: the sourcing agent lists active vendors with a contract or history. Above the quote
    threshold it drafts RFQs for a buyer to send and waits for enough quotes (ERPNext supplier
    quotations of the request, or quotes the buyer records with their document). The buyer
    chooses: an on-hold or disabled vendor is refused, and not taking the cheapest quote needs a
    reason. A new vendor opens a linked onboarding case, and its PO waits for it.
  - PO: the PO agent drafts the PO (quote, then contract, then catalogue price) with the coding.
    Above the PO limit the buyer approves it. The case is then **released** (no separate
    sign-off; the people's steps are the checkpoints). After the release the PO agent posts the
    PO to ERPNext, drafts its email for the buyer to send, and waits for the logged
    acknowledgement. The case completes once a fresh snapshot verifies the PO.
  - Onboarding: the vendor gets a signed portal link (`/vendor/<token>`, no account), drafted and
    sent by a person. They upload the W-9/W-8, bank letter and compliance papers. Text documents
    are read (scanned ones: an AP analyst enters them by hand). Numbers are encrypted in the case
    and only masked forms are shown. The tax ID's form and IRS prefix and the name are checked
    (no IRS TIN matching, which needs GIA's registration). Names are screened against the OFAC
    SDN list (`SANCTIONS_LIST_URL`, a daily job or "Load now"); a hit is a blocking review task.
    The AP analyst confirms the bank by phone from an independent number (the last 4 digits must
    match). A different person activates the vendor. On release the supplier (with its contact
    email) is posted to ERPNext and verified by a fresh snapshot. Bank details in an email reply
    raise a blocking review task, and are never used.
- Finance POD AP-3 (Invoice Matching, `finance_pod/flows/ap_invoice_match`), GIA pages 7-8. One
  case per incoming supplier invoice (an ERPNext draft; "open a case for every new invoice" at
  `POST /api/v1/finance/apm/intake`):
  - 3.2: the posting agent validates it and attaches the vendor's document. The duplicate guard
    flags the same vendor with a near-identical number and the same amount, blocking with the
    reason until a person cancels the case or clears the review task.
  - 3.4: the match agent matches each line to its PO line and the submitted receipts within the
    tolerances (price %, quantity, amount; demo values). It routes the invoice: matched, or a
    non-PO invoice, goes to coding (AP-4: released); a variance becomes an exception.
  - 3.5: the exception agent lays the PO, receipt and invoice side by side and drafts the vendor
    query. The buyer accepts, asks for a credit, or amends the PO in ERPNext (no agent ever
    writes a PO). The agent re-matches on a fresh snapshot (it waits for the credit note or the
    amended PO).
  - 3.6: a missing or short receipt goes to the receivers' queue. Their confirmation (a
    phone-friendly form) posts the Purchase Receipt to ERPNext, verified by a fresh snapshot
    before the re-match.
  - A daily job raises a review task on any held invoice untouched for 7 days.
  - Measures: first-pass match rate, exception ageing, duplicates stopped.
  - Every email is drafted by an agent and sent by a person holding the purpose's capacity.
    Postings are handled by the task kind's capacity. Thresholds are versioned policies
    (`PrqPolicy` / `VndPolicy`), **demo values until GIA's**; each case records the version it
    was opened with.
- Demo users from `uv run poe seed` (password = `DEMO_ADMIN_PASSWORD`): `finance.admin@example.com`
  and `demo.user@example.com` (runs AP Invoice; the admin approves).
- Each agent stores its fields as typed columns in its own table (`ap_invoice_runs`); the common
  lifecycle, findings, documents, LLM calls and reviews live in `agent_runs`, `run_flags`,
  `run_documents`, `run_narratives` and `run_reviews`.
- Uploads: only the extracted text and the file's SHA-256 are stored, never the file. Supported:
  text-based PDF, XLSX, CSV/TSV, DOCX, TXT. Scanned PDFs and images are rejected (no OCR yet).
- LLM: pluggable (`LLM_PROVIDER=azure_openai | none`, see `.env.example`). It only explains
  engine results; output is schema-validated, may cite only real fields/documents, and every figure
  it quotes is checked against the source data. With `none`, runs work without explanations.

### Local ERPNext (Finance POD source, dev and demo only)
```bash
uv run poe erpnext-up     # ERPNext v16 on http://localhost:8090 (first start: a few minutes)
uv run poe erpnext-seed   # company "GIA Demo Labs" + demo AP data; prints the app's API key
```
Sign in as `Administrator` / `ERPNEXT_ADMIN_PASSWORD` (default `admin`). ERPNext's own demo data
is only a few masters, so `scripts/erpnext_seed.py` builds what the AP agents need (all
fictional, emails `@example.com`): labs (the "Lab" accounting dimension), departments (cost
centres), grants (Projects with funder, period, restricted fund, allowed item groups), budgets
(one grant nearly used up), suppliers (approved, one blocked, one on hold, one without an email),
contract prices, purchase requests and three quotations, and POs / receipts / supplier invoices
covering a clean match, a price variance, a short delivery billed in full, a service with no
receipt, a duplicate bill, a non-PO invoice and goods received but not invoiced. Reruns are safe.
"Maintain same rate" is off in Buying Settings so differing invoices can arrive as drafts.
`erpnext-down` stops it; `erpnext-reset` deletes its data. It needs about 600 MB of Docker memory.

Connect it under Data Sources → Connect ERPNext (address, company, the API key and secret the
seed prints; from the app in Docker use `http://host.docker.internal:8090`). The key is checked
before saving and the secret is encrypted with `DATA_ENCRYPTION_KEY`; in production the address
must be https and listed in `ERPNEXT_ALLOWED_HOSTS`. A Finance Admin then takes a read-only
snapshot on the Finance POD dashboard (`POST /api/v1/pod/snapshots/erpnext`): vendors (status and
verified email), items, buying and contract prices, vendor contracts, cost centres, labs, grants,
budgets and their GL actuals, and the last 400 days of purchase requests, supplier quotations,
POs, receipts and supplier invoices with their lines and links. A "demo data" connection makes
demo-labelled snapshots. Approved `create_supplier` / `create_purchase_order` posting tasks are
posted by the app (`post` action): created with `finance_acc_ref` set to the task key (a retry
finds the first attempt's document), submitted when submittable, and verified, like a manual
posting, only by a later snapshot that contains them.

### Viewing the database
- **VS Code:** accept the recommended extensions (*SQLTools* + *SQLTools PostgreSQL*), open the
  SQLTools sidebar and pick **FinanceACC (local docker)**. It's preconfigured in `.vscode/settings.json`.
- **JetBrains (PyCharm/DataGrip):** Database tool window → `+` → PostgreSQL →
  `localhost:5434`, db `finance_acc`, user/password `finance`.
- **Terminal:** `uv run poe db-shell` (psql).

---

## Everyday commands

```bash
uv run poe              # list every task
uv run poe check        # lint + format check + typecheck + tests (same as CI)
uv run poe test-cov     # coverage report → .cache/coverage/html
uv run poe lint-fix     # auto-fix ruff + eslint
uv run poe format       # ruff format

uv run poe migration "add runs table"   # autogenerate an Alembic migration
uv run poe migrate                      # apply migrations
uv run poe downgrade                    # roll back one

uv run poe docker-reset # stop dev stack and wipe the DB volume
uv run poe clean        # delete .cache, __pycache__, frontend dist
```

All tool caches (pytest, ruff, mypy, coverage) go to a single git-ignored `.cache/` folder.

---

## Production

```bash
uv run poe env-init         # then set real SECRET_KEY, POSTGRES_PASSWORD, AZURE_OPENAI_API_KEY
uv run poe docker-prod-up   # docker compose -f docker-compose.prod.yml up -d --build
```

Production stack (`docker-compose.prod.yml`):
1. `db`: Postgres with a healthcheck and a persistent volume, internal network only
2. `migrate`: one-off `alembic upgrade head`, must succeed before the backend starts
3. `backend`: non-root, no dev deps, `WEB_CONCURRENCY` uvicorn workers, healthcheck on `/health`
4. `frontend`: static build on unprivileged nginx, `/api` reverse proxy, security headers and caching

Only the frontend port (`FRONTEND_PORT`, default 8081) is published.

---

## Project layout

```
.
├── src/
│   ├── app/                 # FastAPI backend (entrypoint: src/app/main.py)
│   │   ├── core/            # infrastructure: config, db session, error handling
│   │   ├── common/          # shared building blocks: Base model, mixins, request context
│   │   ├── auth/            # feature: models, schemas, service, router, dependencies
│   │   ├── audit/           # feature: audit events
│   │   ├── cli/             # management commands (seed)
│   │   └── router.py        # registers every feature router under /api/v1
│   ├── db_migration/        # Alembic: env.py + versions/ (DB URL read from DATABASE_URL)
│   ├── frontend/            # Vite + React app (own Dockerfile + nginx.conf)
│   │   └── src/features/    # one folder per feature (auth, dashboard, ...)
│   ├── Dockerfile           # backend image: targets dev | runtime (context = repo root)
│   └── Dockerfile.dockerignore
├── tests/                   # pytest
├── scripts/dev.py           # cross-platform helpers used by poe tasks
├── alembic.ini              # points at src/db_migration
├── pyproject.toml           # deps, tool config, poe tasks
├── docker-compose.yml       # dev stack
├── docker-compose.prod.yml  # prod stack
└── .github/workflows/ci.yml # lint, types, tests, image builds
```

## Conventions
- Secrets live only in `.env` (git-ignored). Add every new variable to `.env.example`.
- Money arithmetic uses `Decimal`, never `float`. Timestamps are timezone-aware (ruff `DTZ` enforces this).
- The LLM is used only for narratives. It never does finance arithmetic, approvals or postings.
- Backend API routes live under `/api/v1/...` so the dev proxy and nginx forward them.
