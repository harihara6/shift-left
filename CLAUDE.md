# ShiftLeft Quality & Delivery Observability Platform

Internal Backbase platform that reads engineering systems (Jira, Confluence, Xray, GitHub, CI, LinearB…),
normalizes them into a canonical model, and renders six dashboard perspectives. The point of the product
is **evidence over flow**: whether a feature is actually done, not whether it looks fast.

## Sources of truth — read before changing behaviour

| File | What it governs |
|---|---|
| `docs/PRD-ShiftLeft-Quality-Observability-Platform.md` | Product requirements. §5 taxonomy, §6 evidence spec, §8 cross-cutting, §9 actionability. |
| `docs/TDD-ShiftLeft-Quality-Observability-Service.md` | Technical design. §5 authz, §6 connector contract, §7 rule pack, §8 actions, §9 entities. |
| `design/DESIGN-HANDOFF.md` | Visual system, screen inventory, UI data shapes, implementation gotchas. |
| `design/ShiftLeft Platform.dc.html` | The clickable prototype — markup, all seed data, all interaction logic. Read the data consts here when porting a screen. |
| `design/Chart.dc.html` | The single chart renderer (grouped bars + multi-series line). |
| `design/original-prototype.html` | Earlier HTML prototype Team Insights was ported from. |

Design files are reference, not build inputs. Never edit `design/`.

## Stack (deviates from the TDD — deliberate)

The TDD §10 recommends Java 21 / Spring Boot + React. **This build uses Python + Angular instead**, by
the project owner's decision. Everything else in the TDD (entities, connector contract, authz model,
freshness rules) carries forward unchanged.

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic v2.
- **DB**: PostgreSQL. Redis for query/connector-state cache.
- **Frontend**: Angular (standalone components, signals, typed reactive forms). No component library —
  the design system in `design/DESIGN-HANDOFF.md` §3 is implemented as CSS custom properties + local components.
- **API client**: generated from FastAPI's OpenAPI schema. Do not hand-write DTOs that already exist server-side.
- **Layout**: `backend/` (FastAPI service), `frontend/` (Angular app), `docs/`, `design/`.

## Non-negotiable product rules

These are enforced in code, not documentation. A change that breaks one of these is wrong even if it passes tests.

1. **Missing is never green.** Absent data renders `Missing`; a connector past its staleness threshold renders
   `Stale` (amber) and is structurally incapable of contributing to a green RAG state. No silent zeros.
2. **RAG resolves to a list, never a score.** `rule_results` carries the literal reason list as a first-class
   field. "Why this is red" is data from the API, never derived at render time.
3. **Every metric drills down.** A widget with no source link is a claim, not a signal. Every number carries a
   drill-down template resolving to a Jira issue / Xray execution / PR / CI run.
4. **Scoped-out ≠ passed.** Waived artifacts leave the denominator (so the percentage stays honest) and are
   listed separately with owner, timestamp, rationale. Deny-listed rationales (e.g. "capacity pressure") render flagged.
5. **Evidence outranks flow, structurally.** Flow screens (Execution Health, Team Insights) carry a persistent
   banner and a cross-link into the Engineering Discipline record. Reviews never open on a flow view.
6. **AI drafts, humans accept.** AI output is labeled, paired with the evidence it drew from, and counts toward
   nothing until a named person's acceptance is recorded.
7. **Templates deep-copy on enable.** No runtime coupling afterward; template edits never reach a live dashboard.
   Origin metadata is traceability only.
8. **Access is project-scoped, never per widget.** Authorization is evaluated at the API layer on every read and
   write — not hidden in the UI. Roles: `viewer`, `contributor`, `admin`, plus an audited `platform-admin` set.
9. **Secrets are write-only.** Credentials render as vault placeholders with a Rotate action. There is no reveal
   endpoint and no reveal affordance. Never log or return a secret value.
10. **Sensitive evidence is status-only.** Threat models, unresolved security findings and pen-test evidence are
    stored as presence + status. Content never leaves the source system.
11. **Every widget ships with its guide.** Four fixed fields stored beside the widget definition: decision supported /
    where it comes from / how it is fetched / how to tag it at source. A widget without them cannot ship.

## Taxonomy — six perspectives, one template each

| # | Perspective | Template | Phase |
|---|---|---|---|
| 1 | Engineering Discipline *(primary)* | Engineering Discipline & Feature Readiness | 2 |
| 2 | Execution Health | Developer & SDET Flow | 3 |
| 3 | Delivery Control | Engineering Delivery Health (incl. Operational Indicators / **Team Insights**) | 3 |
| 4 | Release & Quality Confidence | Release & Quality Confidence *(merged template)* | 4 |
| 5 | Portfolio Quality | Portfolio & Programme Overview | 5 |
| 6 | Executive Signal | Executive Stakeholder Perspective | 5 |

## Current build order

Build order here departs from the PRD's phasing at the owner's direction — Team Insights first.

1. **Team Insights** (Delivery Control) — Q2/Q3 glance table + four sections (Epics, Stories, MAINT, Pull requests),
   each 4 metric tiles + 2 charts. Flow banner with the cross-link to the evidence record. Widget guide modal.
2. **Settings** — Projects (CRUD, template enable/disable with deep-copy, per-widget query binding + preview,
   drill-down template), Connectors (16 connectors, each with its own auth model and field set — the config form
   is data-driven, not one shared form), Access & SSO (grants CRUD).
3. **Shift-left Rollout** (Evidence) — tracks `docs/PROPOSAL-ShiftLeft-Pivot.md`: stage path with computed exit
   criteria, detection accuracy vs manual audit, surfaces at the point of work, warning outcomes. Thresholds are
   named constants in `backend/app/services/rollout_rules.py`; change the proposal first, then the constant.
4. Everything else follows the PRD phasing.

**Data strategy for this pass:** the prototype's seed data (`DECKS`, `PROJECT_CFG`, `TEMPLATE_DEFS`, `CONNECTORS`,
`ACCESS_MODEL` in `design/ShiftLeft Platform.dc.html`) is ported into Postgres seeds *behind the real API contract*.
The UI talks to the real endpoints from day one; live connectors swap in underneath without changing the API shape.

## Reporting windows — never name a quarter

No screen, payload or fixture may hardcode a period. The page always reports "the selected window
against its baseline", resolved at request time by `backend/app/services/periods.py`.

- **Granularities**: quarter (default), half, year. The fiscal year starts in January
  (`FISCAL_YEAR_START_MONTH`), so fiscal quarters are calendar quarters.
- **Default**: the current period against the one before it. Relative, so it never goes stale.
- **Presets**: previous period · same period last year (the one that survives seasonality) · custom.
- **A period in progress is clamped to the data behind it** (`data_through`), not to today. This is
  what stops a partial quarter reading as a throughput collapse.
- **Counts crossing two windows are compared as rates per week, never raw.** 6 epics against 10 is
  −40% as a count and −10% per week; the rate is what gets judged. `Comparison.caveat` says the
  windows differ — and says counts compare directly when they do not.

**Facts are stored per quarter**, kind `delivery_facts`, one `metrics_snapshots` row per period.
A half or year is assembled in `delivery_facts.combine()`: counts add, mean durations are weighted
by sample size, distributions add bucket by bucket, backlog takes the end-of-window reading.
Medians and P85s come back `None` for an aggregate — an average of medians is not a median, and
absent beats invented.

## RAG is computed, not stored

`backend/app/services/delivery_rules.py` holds every delivery threshold as a named constant, and
each rule returns its criterion in the reason it emits ("On track within 10% slower, watch to 25%").
Never reintroduce a stored RAG letter per field: a status nobody can trace is a score in disguise.

## Team Insights fact shape

Per project, per quarter (`backend/app/seed/data/facts.json`):

- `epics` / `stories` — `avg_cycle_days`, `median_days`, `p85_days`, `sample`, `throughput`,
  `size{labels,count,cycle}`; stories add `weekly{labels,done}`
- `maint` — cycle stats, `opened`, `resolved`, `backlog_end`, `priority{labels,count,cycle}`
- `prs` — `median_cycle_days`, `avg_cycle_days`, `merged`, `small_pct`, `huge_count`,
  `buckets{labels,cycle}`, `cadence{labels,merged}`
- `detection` — `labels`, `pr`, `nightly`, `prod`

Regenerate with `python -m app.seed.generate`. Q2-2026 and Q3-2026 carry every number the design
prototype states, exactly; earlier quarters are generated fixtures. `provenance` on each period
says which, and the generator's docstring says what it derived and why.

## Core entities (TDD §9)

`users`, `projects`, `project_access`, `dashboards`, `dashboard_versions`, `widgets`, `templates`,
`connector_types`, `connector_instances`, `connector_filters`, `ingestion_jobs`, `normalized_artifacts`,
`metrics_snapshots`, `rules`, `rule_results`, `artifact_waivers`, `action_records`, `alert_routes`,
`audit_logs`, `share_links`.

Notes: dashboard config is versioned JSON with searchable metadata in relational columns; audit logging is
append-only and covers access-control changes at a higher sensitivity tier; dashboards soft-delete.

## Connector contract (TDD §6)

Every connector implements: `test_connection()`, `list_capabilities()`, `list_available_filters()`,
`preview_data(filter)`, `sync(filter, mode)`, `map_to_canonical_model()`. Each instance exposes
`last_successful_sync`; past its threshold the UI renders a warning and the instance cannot contribute to green.

## Visual system (details in `design/DESIGN-HANDOFF.md` §3)

Dark rail (`#121316`), light canvas (`#F6F6F4`), white surfaces. One accent `#3355FF` reserved for interaction
and drill-down — status colours are never decorative. Instrument Sans for prose, **JetBrains Mono for every
number, ID, query and timestamp**. Radii 6/7-8/10/12/14/99. Status: good `#147A4B`/`#E7F4ED`,
watch `#A66A00`/`#FBF1DE`, poor `#C2352B`/`#FBEAE7`, neutral `#8A8D95`/`#F1F0EC`.

## Implementation gotchas (learned in the prototype)

- Data tables are CSS grid with `grid-template-columns: minmax(0, Nfr)` — fixed px minimums clip at laptop widths.
- Scrollable flex columns need `flex: 0 0 auto` on children, or children compress instead of the container scrolling.
- Slide-over (660px) and modal (920px max, 86vh) both close on scrim click and Escape.
- Charts: one component, spec-driven, geometry computed outside the render. 640×220 viewBox, 5 gridlines,
  2px strokes, 2.8r dots. Every chart carries a caption naming the source and both axes.

## Accessibility

This tool reports on WCAG 2.2 AA compliance, so it must meet it. Required, not optional:
focus-visible rings, keyboard-reachable table rows (real semantics, not divs), `aria-live` on acknowledge
actions, and **colour-plus-shape for every RAG state** — the prototype's dots are colour-only; add a glyph.

## Conventions

- Source tagging (Jira label `shiftleft-tracked`, Confluence `sl-*` labels, `@L1–@L4` test tags, CI artifact
  names, Figma frames containing the Jira key) is surfaced in every widget guide. It is **proposed, not observed** —
  confirm with the teams before relying on it.
- Fixtures run through Q3 2026, with `data_through` at 30 Aug 2026 and release `2026.3`. Keep new
  fixtures on that frame, and add them per quarter — never as a pre-baked comparison.
- Authorization tests are a required CI suite — API-layer, not UI-level hiding.
- Alembic owns the schema. A model change ships with a migration (`make migration m="..."`);
  `test_migrations_build_exactly_the_schema_the_models_declare` fails otherwise.
- Service-wide configuration (connectors) is platform-admin only (`require_platform_admin`); project
  data goes through `require(role)`. Never gate a write on "signed in" alone.
