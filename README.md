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
- Sessions are per browser tab: the SPA sends its tab's id in `X-Session-Slot` and the httpOnly
  auth cookies are named after it, so an admin and a user can be signed in side by side. A new
  tab opens with the last account used; the user menu's "another account" icon signs in a
  different one in that tab only.
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
