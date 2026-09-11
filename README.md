# ShiftLeft

Backbase's internal quality and delivery observability platform. It reads engineering systems
(Jira, Confluence, Xray, GitHub, CI, LinearB and others), normalizes them into one model, and shows
whether a feature is actually done, not just whether it looks fast.

- **Feature Kickoff**: seven steps from a Confluence PRD to an ordered Jira backlog: the repos you code in and rely on, the compliance you approve, your API docs and third-party APIs, then a Claude analysis of what work lands where. Saved per feature, so it can be reopened and run again. Nothing reaches Jira until someone creates it.
- **Feature Readiness**: per-feature Definition of Ready / Done evidence, with the reasons behind every status.
- **Shift-left Rollout**: how far each team has moved from observing evidence to gating on it.
- **Team Insights**: flow metrics (cycle time, throughput, PR size), always linked back to the evidence.
- **Settings**: projects, connectors and project-scoped access.

See [docs/IMPLEMENTATION-NOTES.md](docs/IMPLEMENTATION-NOTES.md) for what is built and the rules the code enforces.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, SQLAlchemy 2 (async), Pydantic v2 |
| Database | SQLite for local development, PostgreSQL 16 in production |
| Cache | Redis 7 (optional locally) |
| Frontend | Angular 22 (standalone components, signals) |
| Tooling | pytest, Ruff, Angular CLI, Docker Compose |

## Prerequisites

- Python 3.10 or later
- Node.js 22.22+ or 24.15+, with npm (Angular 22's supported range)
- Docker (only if you want to run PostgreSQL and Redis locally)

## Getting started

```bash
make install    # creates backend/.venv and installs frontend packages
make backend    # API on http://localhost:8000
make frontend   # UI on http://localhost:4200 (in a second terminal)
```

Open http://localhost:4200. The database is created and filled with example data on first start, so
every screen has content straight away.

Interactive API docs are at http://localhost:8000/docs.

## Configuration

Settings are read from environment variables prefixed with `SHIFTLEFT_`, or from a `backend/.env` file.
Everything has a working default for local development. List values are JSON, e.g.
`SHIFTLEFT_PLATFORM_ADMINS='["ops@backbase.com"]'`.

| Variable | Default | Purpose |
|---|---|---|
| `SHIFTLEFT_ENVIRONMENT` | `development` | `production` turns on the startup guards below |
| `SHIFTLEFT_DATABASE_URL` | `sqlite+aiosqlite:///./shiftleft.db` | Database connection |
| `SHIFTLEFT_AUTO_CREATE_SCHEMA` | `true` | Create tables from the models on start. Local dev only; Alembic owns the schema elsewhere |
| `SHIFTLEFT_SEED_ON_STARTUP` | `true` | Fill an empty database with example data on start |
| `SHIFTLEFT_AUTH_MODE` | `dev-header` | `dev-header` trusts the identity headers as sent. `trusted-proxy` trusts them only with the proxy secret |
| `SHIFTLEFT_PROXY_SHARED_SECRET` | empty | The secret the SSO proxy sends as `X-ShiftLeft-Proxy-Secret` in `trusted-proxy` mode |
| `SHIFTLEFT_PLATFORM_ADMINS` | `["h.nuti@backbase.com"]` | The audited operator set. Only these people can change connectors |
| `SHIFTLEFT_CORS_ORIGINS` | `["http://localhost:4200"]` | Origins allowed to call the API |
| `SHIFTLEFT_LOG_LEVEL` / `SHIFTLEFT_LOG_JSON` | `INFO` / `false` | Log verbosity, and one JSON object per line for a log pipeline |
| `SHIFTLEFT_DEFAULT_STALENESS_MINUTES` | `30` | Freshness threshold for a connector with no row of its own |
| `SHIFTLEFT_WAIVER_RATIONALE_DENYLIST` | see `config.py` | Waiver rationales that are flagged rather than quietly accepted |
| `SHIFTLEFT_ATLASSIAN_SITE_URL` | empty | Optional. Enables Atlassian Rovo MCP discovery in guided project setup |
| `SHIFTLEFT_ATLASSIAN_MCP_TOKEN` | empty | Optional. Token for Rovo MCP |
| `SHIFTLEFT_ANTHROPIC_API_KEY` | empty | Optional. Enables Claude-assisted matching in guided setup (`pip install -e "backend[ai]"`) |
| `SHIFTLEFT_ANTHROPIC_TIMEOUT_SECONDS` | `30` | How long discovery waits for Claude before falling back to name matching |
| `SHIFTLEFT_KICKOFF_MODEL_TIMEOUT_SECONDS` | `300` | How long Feature Kickoff waits for Claude's analysis before falling back to the rule-based draft (labelled as such) |
| `SHIFTLEFT_ATLASSIAN_EMAIL` / `SHIFTLEFT_ATLASSIAN_API_TOKEN` | empty | Feature Kickoff's fallback Jira/Confluence credential on `SHIFTLEFT_ATLASSIAN_SITE_URL`, used when Settings → Connectors has none: reading the PRD and creating the backlog |
| `SHIFTLEFT_GITHUB_API_URL` / `SHIFTLEFT_GITHUB_TOKEN` | `https://api.github.com` / empty | Feature Kickoff's fallback GitHub token for reading repos, when Settings → Connectors has none. Public repos read without one |
| `SHIFTLEFT_XRAY_BASE_URL` / `SHIFTLEFT_XRAY_CLIENT_ID` / `SHIFTLEFT_XRAY_CLIENT_SECRET` | `https://xray.cloud.getxray.app` / empty | Xray Cloud for Settings → Connectors. EU and AU tenants use their regional host |
| `SHIFTLEFT_CURSOR_API_KEY` | empty | Lists the models on the team's Cursor account on the kickoff page (they run in the editor) |

Without the optional settings those features fall back to simpler behaviour; nothing breaks.

## Database

By default the backend uses a SQLite file, `backend/shiftleft.db`. No database server is needed.

- **First start:** tables are created and seeded with example data from the design prototype.
- **Later starts:** existing data is kept. Data for newly added features is filled in if it's missing.
- **Reset:** stop the backend, delete `backend/shiftleft.db`, and start it again.

Seeded connector sync times are fixed when the file is created, so an old database shows every source
as stale (amber). Resetting it gives fresh timestamps.

To use PostgreSQL instead:

```bash
make dev   # starts PostgreSQL and Redis with Docker Compose
export SHIFTLEFT_DATABASE_URL=postgresql+asyncpg://shiftleft:shiftleft@localhost:5432/shiftleft
make migrate
SHIFTLEFT_AUTO_CREATE_SCHEMA=false make backend
```

### Schema changes

Alembic owns the schema (`backend/migrations/`). After changing a model, generate a migration and
read it before committing:

```bash
make migration m="add widget owner"
```

Autogenerate renders server defaults for the database it compared against. Write `sa.func.now()`
rather than `sa.text('now()')` so the migration runs on SQLite as well as PostgreSQL.
`tests/test_production_readiness.py` fails if the models and the migrations disagree.

## Signing in

**In production** the service sits behind an SSO proxy (for example oauth2-proxy in front of the
frontend container). The proxy authenticates the person and sets `X-ShiftLeft-User`,
`X-ShiftLeft-Groups` and `X-ShiftLeft-Proxy-Secret`. With `SHIFTLEFT_AUTH_MODE=trusted-proxy`, the
API rejects any request without the right proxy secret, so a caller who reaches the service directly
can't claim an identity. The proxy must overwrite these headers on every request, never pass on
values sent by the browser. Production builds of the frontend send no identity headers and have no
identity switcher.

**In development** there is no proxy. The left rail of a development build (`make frontend`) has an
identity switcher that sets who is calling the API:

| Identity | Access |
|---|---|
| `h.nuti@backbase.com` | Platform admin, sees every project |
| `dev@backbase.com` | Contributor on Entitlements |
| `qa@backbase.com` | Viewer on Entitlements |
| `director@backbase.com` | Viewer on Platform Programme |

Every permission check happens in the API, so switching identity changes what comes back. Validating
OIDC tokens in-process instead of trusting a proxy means changing one module: `backend/app/core/security.py`.

Connectors belong to no single project, so any signed-in user can read them, but only a platform admin
can change their configuration, rotate a credential, test a connection or enable or disable one.

## Deploying

Both services ship as container images (`make images`):

- **`backend/Dockerfile`** runs as a non-root user and defaults to `SHIFTLEFT_ENVIRONMENT=production`.
  In production mode the service **refuses to start** unless auth is `trusted-proxy` with a proxy
  secret, the database is PostgreSQL, seeding and `create_all` are off, CORS isn't `*`, and at least
  one platform admin is named.
- **`frontend/Dockerfile`** builds the production bundle and serves it from unprivileged nginx on port
  8080, with a Content-Security-Policy and other security headers. It proxies `/api` to `BACKEND_URL`
  (default `http://backend:8000`).

Apply migrations before a new backend version takes traffic:

```bash
docker run --rm -e SHIFTLEFT_DATABASE_URL=... -e SHIFTLEFT_PROXY_SHARED_SECRET=... shiftleft-backend alembic upgrade head
```

Probes: `GET /health` is liveness and touches nothing else. `GET /health/ready` returns 503 when the
database can't be reached. Every response carries an `X-Request-ID`, which is taken from the proxy if it
sent one. The same id appears on every log line, and in the body of any 500.

## Testing and linting

```bash
make test   # backend tests (pytest) and a production build of the frontend
make lint   # Ruff on the backend
```

The authorization tests (`backend/tests/test_authorization.py`) are a required CI suite.
`.github/workflows/ci.yml` runs them as their own step. The workflow also lints, runs the rest of
the suite, round-trips the migrations on PostgreSQL, builds the frontend, and builds both images.

## Project structure

```
backend/
  app/
    api/routes/     HTTP endpoints
    connectors/     connector contract and implementations
    core/           configuration, authorization, logging
    models/         SQLAlchemy tables
    schemas/        API request and response shapes
    services/       business logic and rules
    seed/           example data and loader
  migrations/       Alembic migrations (the schema of record)
  tests/            pytest suite
frontend/
  src/app/
    core/           API client, types, session
    pages/          one folder per screen
    ui/             shared components (tiles, charts, badges)
docs/               PRD, TDD, proposal, implementation notes
design/             clickable prototype and design handoff (reference only, never edited)
```

## Documentation

| Document | Contents |
|---|---|
| [PRD](docs/PRD-ShiftLeft-Quality-Observability-Platform.md) | Product requirements |
| [TDD](docs/TDD-ShiftLeft-Quality-Observability-Service.md) | Technical design |
| [Pivot proposal](docs/PROPOSAL-ShiftLeft-Pivot.md) | Proposed shift from dashboards to enforcement at the point of work |
| [Implementation notes](docs/IMPLEMENTATION-NOTES.md) | What is built, and the rules the code enforces |
| [Design handoff](design/DESIGN-HANDOFF.md) | Visual system and screen inventory |
| [CLAUDE.md](CLAUDE.md) | Working rules for this repository |
