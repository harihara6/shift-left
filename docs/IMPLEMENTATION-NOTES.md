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
| **Feature Kickoff** (Evidence) | Takes a PRD from Confluence to a checked, tagged plan ([proposal](PROPOSAL-PRD-Intake.md)). Six steps: pick the PRD and the model that reads it; confirm the facts it states (each quoted); choose what to do, from actions resolved by rules to Recommended, Not applicable or Needs your answer; run the checks (dependencies in GitHub, third-party readiness, the API standards that apply to the region); review the plan (Jira backlog with the tier's evidence tasks, Xray tests, Confluence pages, software catalog and product index diffs, waiver drafts); confirm. By default it reads example pages (`seed/data/kickoff.json`) and confirming is a dry run. Live (`SHIFTLEFT_KICKOFF_SOURCES=live`, `SHIFTLEFT_KICKOFF_WRITE_MODE=live`) it reads PRDs and the catalog table from Confluence, each service's OpenAPI spec from GitHub at a pinned commit, and writes the epic, stories and evidence tasks to Jira, tests and the test plan to Xray, pages under the PRD, and the catalog row by row. Every item ends created, updated, already there, handed off or failed; failures are retried without duplicates. The product index is read through a parser still to be written, and its rows are handed off. |
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
- **A kickoff decides from the PRD, and says why.** Every action resolves to Recommended, Not
  applicable (naming the fact that ruled it out) or Needs your answer, which runs until answered.
  Leaving a recommended action out needs a reason, and a deny-listed reason is flagged. A fact
  without a verbatim PRD quote is dropped, and a model can only return values from a closed list.
  The checks never say "feasible": they list what was found and what wasn't checked. Nothing is
  written until a named person confirms, and every plan item says what it was drawn from
  (`app/services/kickoff_rules.py`, `app/services/kickoff.py`).
- **A confirmed plan is written exactly as confirmed, and only where it may be.** The plan is frozen
  and the confirmation committed before the first write; retries apply that plan, never a recomputed
  one. Writes stay in the kickoff's own Jira project and space plus the catalog page; work for
  another team is handed off as a drafted request. Example pages can never reach a live backlog: the
  settings refuse live writes without live reads, and a session that read examples can't write live
  (`app/services/kickoff_write.py`, `app/core/config.py`).
- **Every rendered widget has its four guide fields.** The service refuses to boot otherwise
  (`app/services/guides.py`). Catalog template widgets carry their guide key too, so a template
  enabled after seeding copies widgets that still have their guides.
- **No release is pinned.** Feature Readiness defaults to the newest release the project tracks
  features in. Release names compare as numbers, so 2026.10 comes after 2026.9.

## How the optional integrations degrade

| Integration | Without it |
|---|---|
| Atlassian Rovo MCP | Guided setup falls back to the connectors for discovery. Rovo MCP is Atlassian Cloud only and has to be enabled by an org admin. It reads with the caller's own permissions and is used for discovery only; ingestion stays on the REST connectors. |
| Model provider for Feature Kickoff | The model list is fetched from the provider on request. Without an Anthropic key, Claude is listed as unavailable and the rule-based reader is used; a failed model call falls back to it and says so. Cursor's models are listed when `SHIFTLEFT_CURSOR_API_KEY` is set; they run in the editor, since Cursor's API can't answer a prompt directly. |
| Feature Kickoff live sources | A live source that isn't configured or can't be read makes its checks read Not checked with the reason; it never falls back to example data. The product index reads as unavailable until its parser is written. |
| Feature Kickoff live writes | A preflight refuses before the first write if an issue type or required field is missing. An item that fails is recorded as failed with Jira's or Confluence's reason, and the kickoff reads Partial until a retry succeeds. The catalog is not written if its version changed since the plan was drafted. |
| Anthropic API (Claude) | Candidate resolution falls back to deterministic name matching, and the draft says so on screen. Claude only ever chooses among identifiers a source returned; it never writes a query. |

## Seed data

The store seeds itself from the design prototype's data behind the real API contract, so live connectors can
swap in without changing the API. Fixtures run through Q3 2026, with `data_through` at 30 Aug 2026 and release
`2026.3`. Team Insights facts are regenerated with `python -m app.seed.generate`; rollout fixtures are in
`backend/app/seed/data/rollout.json`.
