# Implementation notes

What is built so far, and the product rules the code enforces. For setup and running the project, see the
[README](../README.md). Requirements live in the [PRD](PRD-ShiftLeft-Quality-Observability-Platform.md)
and [TDD](TDD-ShiftLeft-Quality-Observability-Service.md); the proposed change of direction is in
[PROPOSAL-ShiftLeft-Pivot.md](PROPOSAL-ShiftLeft-Pivot.md).

## Stack deviation

The TDD (§10) recommends Java 21 / Spring Boot + React. This build uses Python + Angular instead, by the
project owner's decision. Everything else in the TDD carries forward unchanged: entities, connector
contract, authorization model and freshness rules.

## What is built

| Area | State |
|---|---|
| **Feature Readiness** (Engineering Discipline) | Evidence of record. Four completeness tiles and a feature table (Ready/Done evidence bars, status and reason). Opening a feature shows a slide-over with the eleven-row evidence checklist, the why-red list, an AI draft that needs recorded acceptance, and the owner and next action. Waivers and open actions sit beside the table. |
| **Shift-left Rollout** (Evidence) | Tracks the [pivot proposal](PROPOSAL-ShiftLeft-Pivot.md). Shows the gating path (Observe → Warn → Soft gate → Hard gate) with computed exit criteria and audited sign-off / advance / roll back. Tiles for detection accuracy against a manual audit, false-red rate and warnings resolved with evidence. Also lists the surfaces where the engine shows up (Jira panel, transition check, PR check, Slack digest, Confluence templates), detection by artifact, and accuracy and warning-outcome charts. |
| **Team Insights** (Delivery Control) | Glance table plus Epics / Stories / MAINT / Pull requests sections, each with tiles and charts. Freshness strip, flow banner and a guide for each widget. |
| **Reporting window filter** | Quarter / half / year, defaulting to the current period against the previous one. Presets for the preceding period and the same period last year, plus a custom range. One control, top right, governs the whole page. |
| **Settings → Projects** | Project CRUD, archive (soft delete), duplicate, template enable/disable with deep copy, per-widget query binding with live preview. |
| **Settings → Guided project setup** | An optional alternative to the manual form. It searches every source that can look a team up by name (Atlassian Rovo MCP where it's enabled, the connectors otherwise). It proposes the project identity, templates and per-widget queries with the evidence behind each, and creates nothing until a named person accepts it. |
| **Settings → Connectors** | 16 connector types, each with its own auth model and data-driven field set. Test connection, write-only credential rotation, enable/disable. |
| **Settings → Access & SSO** | Project-scoped grants (add/revoke, last-admin protection) and the written model. |
| Other four perspectives | Not built. See the build order in [CLAUDE.md](../CLAUDE.md). |

## Rules the code enforces

These are checked by tests, not just written down. See `backend/tests/`.

- **Scoped-out is not passed.** Waived artifacts leave the denominator and are reported with owner,
  timestamp and rationale. A rationale on the deny-list is flagged rather than quietly accepted.
- **AI drafts, humans accept.** An AI draft counts toward no gate until a named person's acceptance
  is recorded and audited.
- **Missing is never green.** Stale or absent sources are held out of a green state, and the
  downgrade says why (`app/services/freshness.py`).
- **No period is hardcoded.** Every window is resolved at request time, and a period still in
  progress is measured by the data it has, not by the calendar (`app/services/periods.py`).
- **Counts across unequal windows are compared as rates.** A short quarter never reads as a
  collapse. The caveat appears only when the windows actually differ.
- **Status resolves to reasons, never a score.** Every `RagState` carries its reason list.
- **Colour is never the only signal.** Each state ships a glyph (WCAG 2.2 AA).
- **Authorization at the API layer.** Project-scoped roles apply on every read and write. An unauthorized
  caller gets a 404, learning nothing about what exists. Connectors belong to no project, so changing
  one (config, credential, test, enable or disable) needs a platform admin, and anyone else gets a 403.
  Platform admins are configured (`SHIFTLEFT_PLATFORM_ADMINS`), never granted through the API
  (`app/core/security.py`).
- **Identity is trusted only when the SSO proxy vouches for it.** In `trusted-proxy` mode the identity
  headers count only alongside the proxy's shared secret. A production deployment refuses to start in
  any other mode, or with SQLite, seeding, `create_all` or wildcard CORS (`app/core/config.py`).
- **Secrets are write-only.** Credentials return a vault placeholder; there is no read path. A
  connector's config accepts only the fields that connector declares, and only an http(s) base URL
  ever becomes a drill-down link.
- **Alembic owns the schema.** `backend/migrations/` is the schema of record, and a test fails if the
  models and the migrations disagree.
- **Templates deep-copy on enable.** Editing a catalog template never reaches a live project.
- **A guided setup proposes; it never applies.** Discovery writes no project, dashboard or binding, and
  a draft is readable only by whoever ran it. If nothing was discovered for a widget, its query is left
  empty rather than inheriting the template's exemplar: pointing a new project at another team's data
  would look finished and be wrong (`app/services/onboarding.py`).
- **A rollout stage is earned, not assumed.** A stage is advanced only when every exit criterion is met,
  and a refusal returns the unmet criteria as a list. A surface that is correctly off reads "Not due yet",
  not healthy (`app/services/rollout_rules.py`).
- **Every rendered widget has its four guide fields.** The service refuses to boot otherwise
  (`app/services/guides.py`). Catalog template widgets carry their guide key too, so a template
  enabled after seeding copies widgets that still have their guides.
- **No release is pinned.** Feature Readiness defaults to the newest release the project tracks
  features in. Release names compare as numbers, so 2026.10 comes after 2026.9.

## How the optional integrations degrade

| Integration | Without it |
|---|---|
| Atlassian Rovo MCP | Guided setup falls back to the connectors for discovery. Rovo MCP is Atlassian Cloud only and has to be enabled by an org admin. It reads with the caller's own permissions and is used for discovery only; ingestion stays on the REST connectors. |
| Anthropic API (Claude) | Candidate resolution falls back to deterministic name matching, and the draft says so on screen. Claude only ever chooses among identifiers a source returned; it never writes a query. |

## Seed data

The store seeds itself from the design prototype's data behind the real API contract, so live connectors can
swap in without changing the API. Fixtures run through Q3 2026, with `data_through` at 30 Aug 2026 and release
`2026.3`. Team Insights facts are regenerated with `python -m app.seed.generate`; rollout fixtures are in
`backend/app/seed/data/rollout.json`.
