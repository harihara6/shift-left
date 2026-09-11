# Technical Design Document — ShiftLeft Quality Observability Service

**Status:** Draft for review
**Implements:** PRD — ShiftLeft Quality & Delivery Observability Platform
**Feeds into:** Claude Design UI prototype
**Supersedes:** the original ShiftLeft Quality Observability Service TDD (retained conceptually where unchanged; deltas called out explicitly below)

---

## 0. What changed from the original TDD

The original TDD is mostly good engineering and is reused wherever it doesn't conflict with the PRD. Three things changed because the PRD made them binding:

1. **RBAC is now in scope for v1.** The original TDD proposed shipping with global visibility and "add project-level controls in a later phase." The PRD reclassified this as launch-blocking (it surfaces threat-model and security evidence to every authenticated user). §5 below is the actual design, not a deferred risk note.
2. **Engineering Discipline & Feature Readiness is now Phase 2, alone** — not bundled with Execution Health and Delivery Control. It's the perspective every other view drills back into, so it has to exist before the others are trustworthy.
3. **Quality & Test Confidence and Release Readiness merged into one template** (Release & Quality Confidence), per PRD §5. One connector set, one dashboard, not two answering the same question.
4. **Actionability is now a data-model and API concern**, not just a UI convention — owners, next actions, and alert routing are first-class entities (§8), not text fields.

Everything else — the six-layer architecture, the connector contract, the core entity list, the tech stack recommendation — carries forward from the original TDD largely unchanged, and is restated here for completeness so this document stands alone.

---

## 1. Scope

Build a Backbase-hosted service at `shiftleft.backbase.com` that:

- connects to engineering systems through versioned connectors,
- normalizes data into a canonical model,
- lets authenticated, **authorized** Backbasers create projects and dashboards scoped to what they're permitted to see,
- ships six perspective templates matching the PRD taxonomy exactly (not eight),
- treats Engineering Discipline evidence as the record every other perspective links back to,
- and turns red/breached states into owned, tracked actions rather than passive reporting.

---

## 2. Architecture (six layers, unchanged in shape)

1. **Web UI** — project/dashboard management, template-based creation, rule configuration, audit-log browsing. *(Design handoff target for Claude Design.)*
2. **Gateway and API layer** — secure APIs for UI operations, connector management, dashboard CRUD, rule management, query execution. Now also enforces authorization (§5) on every call, not just authentication.
3. **Connector layer** — pluggable integrations (§6).
4. **Normalization and metrics engine** — canonical model, KPIs, trends, completeness signals, RAG status, risk-tier evaluation.
5. **Persistence layer** — metadata, connector configs, normalized facts, dashboard definitions, templates, audit logs, cached queries, **access-control state**, **action/ownership records**.
6. **AI support services** — summarization, clustering, anomaly explanation, engineering-discipline drafting assistance. Every output here is labeled, evidence-linked, and requires recorded human acceptance before it counts toward a gate (PRD §8).

**Architectural principle carried forward unchanged:** keep source connectivity, data normalization, and dashboard rendering independently evolvable.

---

## 3. Domain responsibilities

| Domain | Responsibility | Key outputs | Note |
|---|---|---|---|
| Identity and session | Backbase SSO login, session, token validation | User session, profile, audit identity | Unchanged |
| **Authorization** | Resolve project/team scope per request | Access decision per resource | **New — replaces "no per-resource authorization in v1"** |
| Project management | Create/manage projects containing dashboards and connectors | Project records, ownership metadata | Ownership now drives default access scope |
| Dashboard management | CRUD for dashboards, widgets, layouts, filters, rules, links | Dashboard definitions, versions, permalinks | Unchanged |
| Template catalog | Six PRD-aligned stakeholder templates | Template definitions, versioned defaults | Reduced from 8 to 6 — see §4 |
| Connector management | Register, validate, schedule, query sources | Connector instances, sync state, schemas | Unchanged |
| Quality rules engine | RAG thresholds, engineering-discipline checks, risk-tier scoping | Rule results, badge states, policy violations | Unchanged in mechanics |
| Metrics and aggregation | KPIs, trends, rollups | Aggregated metrics, time series | Unchanged |
| **Action and ownership** | Track owner + next action per red/breached signal, route alerts | Action records, alert dispatch log | **New — implements PRD §9** |
| Audit logging | Who changed what in dashboard CRUD and access grants | Immutable change log | Extended to cover access-control changes |
| AI insights | Summaries, clustering, anomaly explanation, completeness analysis | Insight cards, suggestions | Assistive only, per PRD §8 |

---

## 4. Template catalog — six, matching the PRD exactly

| Template | Perspective | Primary audience | Default connectors | Status |
|---|---|---|---|---|
| **Engineering Discipline & Feature Readiness** | Engineering Discipline *(primary)* | ETLs, PMs, architects | Jira, Confluence, Xray, GitHub/Bitbucket, CI | **Build first — Phase 2** |
| Developer & SDET Flow | Execution Health | Devs, SDETs, tech leads | GitHub/Bitbucket, SonarQube, CI, Xray | Phase 3 |
| Engineering Delivery Health (incl. Operational Indicators sub-view) | Delivery Control | Eng managers, delivery leads, PMs | Jira, GitHub/Bitbucket, CI/CD, LinearB | Phase 3 |
| Release & Quality Confidence *(merged)* | Release & Quality Confidence | QA leads, SDETs, release managers | Xray, CI, SonarQube, perf/a11y runners, deployment tools | Phase 4 |
| Portfolio & Programme Overview | Portfolio Quality | Directors, programme leads | Jira, Confluence, CI/CD, portfolio-planning tools | Phase 5 |
| Executive Stakeholder Perspective | Executive Signal | VP Eng, CTO, CPO, CEO | Aggregated project dashboards, observability, incident tools | Phase 5 |

**Template behavior (unchanged from original TDD, still correct):**
- Deep-copy creation — layout, widgets, connector bindings, filters, rules, thresholds copied into a new dashboard.
- Complete independence after creation — template edits never propagate.
- Origin metadata retained for traceability only, never for sync.
- Unmapped connectors on creation render a pending-connection state, never empty-as-if-zero.
- Every template ships with: audience, decision supported, data-freshness expectation, interpretation guide, required connectors, known limitations.

---

## 5. Authorization design (new — this is the PRD's launch-blocking fix)

**Model:** project-scoped roles, inherited from Backbase SSO groups where possible, explicit grants where not.

- **Roles:** `viewer`, `contributor` (can edit dashboards/rules within a project), `admin` (can manage connectors, access grants, and template governance for a project). No global role bypasses project scope except a small, audited `platform-admin` set for the service's own operators.
- **Resource scoping:** every dashboard, connector instance, and rule belongs to exactly one project. Authorization is evaluated at the API layer on every read and write — not just enforced in the UI.
- **Sensitive-field handling:** threat-model status, unresolved security findings, and pen-test evidence are treated as **presence-and-status indicators with drill-down restricted to the source system**, per the PRD's carry-forward of the original TDD's own risk note — the platform does not mirror their full content, only whether evidence exists and its status.
- **Group-to-project mapping:** SSO group membership seeds default project access on first login for a project's team; explicit per-user grants layer on top for cross-team reviewers (e.g., a portfolio director needs read access across many projects without joining every team's SSO group).
- **Audit:** every access grant/revoke is an immutable audit-log entry, filterable the same way dashboard CRUD is.

This closes the original TDD's top-listed risk (over-broad visibility, "High" impact) at launch instead of "in a later phase."

---

## 6. Connector layer (unchanged mechanics, retained in full)

Standard contract per connector:

```
testConnection()
listCapabilities()
listAvailableFilters()
previewData(filter)
sync(filter, mode)
mapToCanonicalModel()
```

Builder flow: select project → add/reuse connector instance → configure scope/filters → preview → map to widget or rule → save as dashboard-level query or reusable project filter.

**Connector priority order (Phase 1, matches PRD phasing):** Jira, Confluence, Xray, GitHub/Bitbucket, CI pipeline engines. Everything else (SonarQube, security scanners, deployment orchestrators, observability platforms, LinearB, design tools) follows as each perspective phase requires it — the original TDD's full connector table (Jira, Product Discovery, Confluence, Knowledge vault, GitHub, Bitbucket, Figma, Design System, SonarQube, security scanners, CI, feature flags, JUnit, Postman, Playwright, Cypress, performance runners, TestRail, Xray, Allure, JSM, Caboose, GitHub Deployments, Azure, Kubernetes, ArgoCD, Harness, security/compliance repos, Datadog, Dynatrace, Grafana, Sentry, PagerDuty, repos/CI-CD, AI/LLM telemetry) is unchanged and carries forward as the full target list.

**Freshness requirement (PRD §8):** every connector instance exposes last-successful-sync timestamp. The UI layer must render a staleness warning past a per-connector threshold; a stale connector never contributes to a green RAG state.

---

## 7. Engineering-discipline rule pack (build spec for Phase 2)

Canonical feature structure (unchanged from PRD §6 / original TDD):

| Section | Expected artifact | Typical source |
|---|---|---|
| Feature intent | Problem, objective, scope, stakeholders | Jira / Product Discovery / Confluence |
| Functional acceptance | Acceptance criteria and edge cases | Jira / Confluence |
| Non-functional acceptance | Performance, accessibility, security, reliability | Confluence / Jira |
| Design evidence | Visual designs, HLD, LLD | Confluence / design sources |
| Risk and security | Threat model and controls | Confluence / security repositories |
| Verification | Test plan, Xray traceability, automated results | Xray / CI / test tools |
| Release evidence | Approvals, deployment status, post-deploy checks | CI/CD / deployment / Jira |

**Risk-tier evaluation logic:**
- Tier resolved from change classification (new capability / major / minor / config-copy) at Ready.
- Full artifact set required for new capability and major change; no scoping down offered for new capability.
- Ambiguous tier defaults to the higher tier — implemented as: if the automated classifier's confidence is below threshold, present a decision list to the accountable ETL rather than silently picking the lower tier.
- Every omission writes an `artifact_waivers` record: artifact, tier, decision owner, rationale, timestamp. Rationale is free text but indexed/reportable so patterns (e.g., repeated "capacity pressure" entries) surface to platform owners as a planning signal, per PRD §6.

**RAG computation:** composed transparently from the checklist above — never a hidden weighted score. UI must be able to show "why red" as a literal list of missing artifacts, not a number.

---

## 8. Action and ownership model (new — implements PRD §9)

New first-class concept: an **action record**, created automatically whenever a rule evaluates to red or a threshold breaches.

- Fields: `signal_id`, `dashboard_id`, `owner` (person or team, resolved from project roles — never a placeholder), `next_action` (short text, required), `status` (open/acknowledged/resolved), `created_at`, `acknowledged_at`, `resolved_at`.
- High-severity categories (security findings, threat-model gaps, release-blocking defects) auto-dispatch to a configured channel (Slack webhook or Jira Service Management ticket in v1; PagerDuty integration deferred — see open decisions) rather than waiting for someone to open the dashboard.
- Review-cadence enforcement: the API exposes an explicit "open review" entry point per project that defaults to the Engineering Discipline dashboard — matching the PRD's requirement that reviews never open on a flow-only view.
- Behavior-change tracking: action records feed the "reporting without behavior change" counter-metric from PRD §11 — time-to-acknowledge and time-to-resolve trends are themselves a dashboard signal, not just an operational log.

---

## 9. Database design

Hybrid model, unchanged in spirit from the original TDD, extended for authorization and actionability.

**Core entities (carried forward):**
`users`, `projects`, `dashboards`, `dashboard_versions`, `widgets`, `templates`, `connector_types`, `connector_instances`, `connector_filters`, `ingestion_jobs`, `normalized_artifacts`, `metrics_snapshots`, `rules`, `rule_results`, `artifact_waivers`, `audit_logs`, `share_links`.

**New entities (this TDD):**
- `project_access` — user or SSO-group → project → role, granted_by, granted_at.
- `action_records` — as specified in §8.
- `alert_routes` — project → severity category → destination (Slack channel, JSM project, future PagerDuty service).

**Design notes (unchanged, still correct):**
- Dashboard configuration stored as versioned JSON, searchable metadata in relational columns.
- Append-only audit logging, extended to access-control changes.
- Soft delete for dashboards.
- Precomputed aggregates for fast loads.
- Normalized source references so widgets always drill down to evidence.

---

## 10. Tech stack (unchanged recommendation)

| Layer | Technology | Reason |
|---|---|---|
| Frontend | React + TypeScript | Dynamic dashboard builder, matches Backbase pattern |
| Backend APIs | Java 21, Spring Boot, Spring Security | Internal familiarity, mature integration ecosystem |
| Async processing | Spring Boot workers, queue-based jobs | Scheduled syncs, connector ingestion |
| Database | PostgreSQL | Relational modeling for dashboards, rules, audit, access |
| Search/filtering | OpenSearch or Postgres full-text (v1) | Log search, artifact lookup |
| Cache | Redis | Session-adjacent caching, query caching, connector state |
| Object storage | S3-compatible | Snapshots, exports, evidence bundles |
| Observability | Micrometer + Prometheus/Grafana | Operational consistency |
| Deployment | Kubernetes | Standard internal hosting |
| CI/CD | GitHub Actions or Backbase standard pipelines | Automated build/test/scan/release |

Python remains the recommendation for AI/connector-processing sidecars where FastAPI's speed of iteration matters more than platform consistency (unchanged from original TDD).

**Analytics store:** stays on PostgreSQL for v1 given the dataset size at launch (single-digit projects, six templates). Revisit DuckDB/ClickHouse when metrics_snapshots volume or cross-project query latency justifies the operational cost — flagged as an explicit trigger to monitor (see §13), not a v1 build item.

---

## 11. Security (extended)

Carried forward: TLS everywhere, SSO-only access, encrypted secrets storage, strict outbound allowlists, audit logs for CRUD, input validation/output encoding, CSRF protection, rate limiting, data minimization in caches/logs, secret rotation, dependency/container scanning.

**Added by this TDD:**
- Authorization enforcement at the API layer, tested as a required suite in CI (not just UI-level hiding).
- Access-grant changes are a distinct, higher-sensitivity audit category with longer retention than general dashboard CRUD.
- Sensitive-evidence fields (threat model, security findings) never leave the source system's content in the platform's own storage — only status/presence, per §5.

---

## 12. Release automation (unchanged)

PR validation (unit, integration, UI, security checks) → static analysis/quality gates → signed container images → progressive deployment → DB migration automation → smoke tests → rollback support → release evidence collected into the platform's own Engineering Discipline dashboard, since this service is itself expected to meet the delivery expectations it reports on.

Pipeline: build → unit/component tests → static analysis/SCA → container build/scan → integration tests with mocked connectors → E2E UI tests → deploy non-prod → smoke/synthetic tests → approval if required → production deploy → post-deploy verification.

---

## 13. Risks (PRD-aligned, RBAC removed as "accepted" and closed by design)

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| Over-broad visibility | — | Closed by §5 authorization design | **Resolved in this TDD, not deferred** |
| Connector fragility | High | Version connectors, cache aggressively, monitor failures, isolate adapters | Unchanged |
| Data inconsistency across tools | High | Canonical model, explicit mapping rules | Unchanged |
| Reporting without behavior change | Medium | Action-record tracking (§8) makes this measurable, not just a hope | Mitigation strengthened |
| Flow metrics mistaken for evidence | High | Structural drill-down link + UI banner (design-phase requirement) | Unchanged, now enforced at data-model level via required cross-links |
| Template misuse (assumed live-bound) | Medium | Deep-copy + explicit UI messaging | Unchanged |
| Performance at scale | High | Precomputation, caching, async refresh | Unchanged |
| AI trust issues | Medium | Assistive only, evidence-linked, human acceptance recorded | Unchanged |
| Audit volume growth | Medium | Partition logs, retention policy, indexed filtering by dashboard ID | Unchanged |
| Source credential sprawl | Medium | Central integrations, secret vaulting | Unchanged |
| **Analytics store outgrowing Postgres** | Medium | Documented trigger to revisit (§10) rather than pre-building complexity | **New, explicitly deferred with a tripwire** |

---

## 14. Open decisions carried into design/build

- PagerDuty vs. staying on Slack + JSM for release-blocking alert routing (§8) — affects `alert_routes` schema but not the core model.
- Exact SSO-group-to-project mapping convention (naming pattern vs. manual mapping table) — affects onboarding effort per team.
- Whether `project_access` supports group-based grants at launch or only individual grants with group support in a fast-follow.

---

## 15. Handoff to Claude Design

Design should start from the **Engineering Discipline & Feature Readiness** template (§4, §7) — it's the perspective with no existing visual reference, unlike the other five where the HTML prototype and Operational Indicators spec already establish a visual language to extend. Priority views for the first design pass:

1. Feature-level evidence checklist (the §7 table, rendered as an inspectable per-feature view with drill-down).
2. RAG-with-reasons pattern (why red, as a literal list, not a score).
3. Waiver/rationale display (artifact_waivers) with the reportability requirement visible.
4. The cross-link pattern from a flow widget (existing Team Insights style) to its corresponding Engineering Discipline record — this is the single most important interaction to get right, since it's what makes the evidence-over-flow rule real instead of documented.
