# PRD — ShiftLeft Quality & Delivery Observability Platform

**Status:** Draft for review
**Feeds into:** Technical Design Document → Claude Design UI prototype
**Supersedes/reconciles:** *Backbase Shift-Left with AI Strategy*, *ShiftLeft Quality Observability Service TDD*, *Operational Indicators Team Dashboard Requirements*
**Owner:** TBD (ETL sign-off required before TDD kickoff)

---

## 0. Why this document exists

The three source documents are individually solid but were written at different times with different mental models, and they've drifted apart in three specific ways:

1. The strategy doc defines **6 dashboard perspectives**. The TDD defines **8 templates** with different names and no explicit mapping between the two lists.
2. The most important perspective — the one every other view is supposed to defer to — **Engineering Discipline & Feature Readiness** — is fully specified in prose but has no build spec and no prototype. Everything actually built so far (the HTML prototype, the Operational Indicators spec) is flow telemetry, not evidence.
3. Real product risks are noted almost as asides (no RBAC in v1, stale connectors, AI trust) rather than treated as launch-blocking requirements.

This PRD fixes the taxonomy, promotes the evidence view to a first-class build item, and turns the buried risks into explicit requirements — informed by how mature engineering organizations (Google's DORA research, SRE practice, and the broader industry consensus that's grown around it) actually run this class of tool.

---

## 1. Problem statement

Engineering leadership at Backbase cannot currently answer, in one place and on demand:

- Is a feature actually **done** (evidence), or does it just **look done** (throughput)?
- Where is quality risk concentrated **right now**, at the level each stakeholder needs (PR, team, portfolio, company)?
- Is shift-left behavior **improving** release over release, or is reporting happening without behavior change?

Today this requires manually assembling quarterly decks, verbally asserting evidence status in reviews, and trusting self-reported "done." That doesn't scale, isn't auditable, and actively rewards the wrong thing: a team can look great on flow metrics while shipping unverified work.

## 2. Goals

- Give every stakeholder tier (engineer → CTO) a **live, filterable, no-rebuild** view suited to the decision they actually make.
- Make **Definition of Ready / Definition of Done evidence** a first-class, inspectable, drillable signal — not a verbal claim.
- Make **flow telemetry** (cycle time, throughput, PR size) available for delivery management, structurally incapable of being mistaken for quality evidence.
- Reduce the manual cost of assembling this data to zero after initial setup.
- Close the loop: production learning feeds back into planning automatically.

## 3. Non-goals (v1)

- Not a replacement for Jira/Confluence/Xray/CI as systems of record — it reads from them.
- Not a new approval gate. It reports on Definition of Ready / Definition of Done; it does not decide them.
- Not a cross-company benchmarking tool in v1 (explicitly phased later, and only ever paired with quality signals — see §13).
- Not building custom auth — SSO only, and see §8 for the RBAC decision this PRD forces.

---

## 4. Guiding principles (tightened)

1. **Evidence outranks flow.** Where the two disagree, the evidence view governs. This is enforced in product, not just written in a doc (see §5).
2. **A widget without a drill-down link is a claim, not a signal.** Every metric must resolve to a source record.
3. **A missing connector is a gap, never a pass.** Never render green on absent data.
4. **A composite score is never sufficient on its own for a ship decision.** RAG status must be traceable to visible, configurable criteria.
5. **Depth scales with risk tier, and every omission is written down.** No silent scoping-down.
6. **AI drafts, humans accept.** Every AI-generated artifact or classification is assistive until a named accountable person signs off, and that acceptance is recorded.
7. **A dashboard without an owner and a next action is reporting theater.** See §9.
8. **Templates are opinionated starting points, not live-bound.** Deep-copy on creation; template changes never retroactively alter a shipped dashboard.

---

## 5. The one taxonomy (the core fix)

Six **perspectives** (the "why" — audience and decision). Each perspective has exactly one **primary template** (the "what" — the concrete dashboard). This replaces both the strategy doc's 6-perspective list and the TDD's 8-template list with a single mapping.

| # | Perspective | Decision it supports | Audience | Primary template | Cadence | Build status |
|---|---|---|---|---|---|---|
| 1 | **Engineering Discipline** *(primary/first-class)* | Is this feature allowed to start / ship? | ETL, PM, architects | Engineering Discipline & Feature Readiness | Continuous, gate-triggered | **Not yet built — see §6** |
| 2 | Execution Health | Is today's PR/build/test loop healthy? | Devs, SDETs, tech leads | Developer & SDET Flow | Real-time | Partial (HTML "Shift-left" home) |
| 3 | Delivery Control | Is the team's flow pace and cadence on track? | Eng managers, delivery leads, PMs | Engineering Delivery Health, with Operational Indicators (team flow) as its team-attached sub-view | Weekly / bi-weekly | Prototyped (HTML "Team Insights") |
| 4 | Release & Quality Confidence | Is this release safe to ship? | QA leads, SDETs, release managers | Quality & Test Confidence + Release Readiness (merged into one perspective — they were two templates answering one question) | Per release | Not built |
| 5 | Portfolio Quality | Where are systemic hotspots across teams? | Directors, programme leads | Portfolio & Programme Overview | Monthly / quarterly | Not built |
| 6 | Executive Signal | Is the org's quality trajectory improving? | VP Eng, CTO, CPO, CEO | Executive Stakeholder Perspective | Quarterly | Not built |

**Correction applied:** the old TDD had "Quality and Test Confidence" and "Release Readiness and Operational Confidence" as two separate templates answering essentially the same question for overlapping audiences. Merged to one perspective, one template, to avoid stakeholders needing to know which of two similar dashboards to open.

**Correction applied:** Operational Indicators is not a peer of Delivery Control — it *is* the team-attached, self-service flavor of it. One perspective, not two competing ones.

---

## 6. Perspective 1 spec — Engineering Discipline & Feature Readiness (the missing piece)

This is the evidence-of-record view. It must exist before the platform can honestly claim to "enforce shift-left," because right now nothing in the built artifacts actually checks Definition of Done — everything built checks *speed*.

**Per-feature evidence checklist** (carried forward from the TDD's canonical structure, now the spec of record):

| Artifact | Accountable | Gate | Source |
|---|---|---|---|
| Requirements incl. visual design | PM + Design, ETL assures | Ready | Jira + Confluence + Figma |
| Acceptance criteria incl. NFRs | PM | Ready | Jira |
| Test plan incl. NFR testing | ETL/SDET | Ready | Confluence |
| HLD | ETL | Ready | Confluence |
| LLD (per platform) | ETL + platform engineers | Drafted at Ready, complete at Done | Confluence |
| Threat model | ETL + Security Engineer | Design stage + pre-release | Confluence + threat catalog |
| Traceability matrix | ETL/SDET | Done | Xray |
| Test evidence | ETL/SDET/engineers | Done | Xray + CI |
| Performance | ETL/engineers/SDET | Done | Confluence |
| Accessibility (WCAG 2.2 AA) | ETL + Web/Mobile engineers | Done | CI + Confluence |
| AI-first / T-shaped evidence | ETL assures, every engineer | Both | Recorded human validation |

**Risk-tier scoping** (must ship with the first version, not deferred):

| Tier | Trigger | Requirement |
|---|---|---|
| New capability | New service, journey, or customer-facing feature | Full set. No scoping down offered. |
| Major change | New endpoint, changed data model/trust boundary, new integration | Full set. Threat model may use a recorded refresher instead of a full session. |
| Minor change | Behavior change in an existing, recently-modeled capability | Requirements, AC, test plan, LLD delta, test evidence, touched NFRs. Everything else needs a recorded rationale. |
| Config / copy | No logic change | AC + test evidence. Everything else scoped down with recorded rationale. |
| **Ambiguous** | — | **Defaults to the higher tier.** |

**Waiver model:** every scoped-down artifact is structured data — artifact, tier, decision owner, rationale, timestamp — reportable and reviewable. "Capacity pressure" is explicitly not an acceptable rationale; it's a planning signal that must surface before work starts, not an excuse recorded after.

**RAG logic:** status is computed from the visible checklist above, never a hidden composite. Missing evidence renders as missing, not amber-and-forgotten.

---

## 7. Requirements for the remaining five perspectives

Full widget catalogs already exist and are good — reuse them from the TDD and Operational Indicators docs largely as-is. What this PRD changes is binding, not content:

- **Execution Health** and **Delivery Control** widgets must each carry a persistent link to the Engineering Discipline record for the same feature/team/period. This is not optional decoration — see §5's rule 1.
- **Delivery Control's** Operational Indicators sub-view keeps its existing 11-section spec (side-by-side comparison, epics, stories, MAINT, PRs) unchanged — that document was already clear and doesn't need correction, only re-homing under this taxonomy.
- **Release & Quality Confidence** (merged template) shows: test execution trend, pass/fail, flaky tests, automation coverage, NFR verification, open release-blocking defects, evidence completeness — pulled once, not duplicated across two dashboards.
- **Portfolio Quality** and **Executive Signal** are pure roll-ups. They must never compute their own truth — every number here traces to a lower-perspective record.

---

## 8. Cross-cutting platform requirements

| Area | Requirement | Why |
|---|---|---|
| **Access control** | **RBAC at project/team level is a launch requirement, not a v2 backlog item.** The prior TDD explicitly names threat-model records, unresolved security findings, and pen-test evidence as the most sensitive data the platform holds, then proposes shipping with zero access control. That's the wrong order. Minimum bar: project-scoped visibility at launch; identity-only auth (no authorization) is not acceptable for a tool that surfaces security evidence. | Standard practice at any org that ships internal tooling touching security data — visibility scoping ships with the feature, not after an incident. |
| **Connector freshness** | Every widget shows last-sync time. Staleness past a defined threshold renders as a warning state, never as green, never as silently missing. | Stale-but-green is worse than visibly broken. |
| **Drill-down** | Every metric, no exceptions, links to its source record (Jira issue, Xray execution, PR, CI run). | Makes the dashboard a pointer to truth, not a competing truth. |
| **Template governance** | Templates are versioned and owned. Creating a dashboard from a template deep-copies it; there is no runtime coupling afterward. UI must make this unambiguous to the user. | Prevents "the template changed, why did my dashboard change" confusion. |
| **Audit** | All dashboard CRUD (create/update/duplicate/delete/restore/share/rule-change) is logged immutably, filterable by dashboard ID and actor. | Standard for any tool influencing release decisions. |
| **AI usage** | AI output (scenario drafts, coverage suggestions, summaries, clustering) is labeled as AI-generated, always paired with the evidence it was drawn from, and requires recorded human acceptance before it counts toward any gate. | Keeps "AI-first" from quietly becoming "AI-assumed." |

---

## 9. Actionability requirements (new — this was missing from all three source docs)

A dashboard that only reports is reporting theater — explicitly called out as a risk in the TDD but never turned into a requirement. Fixing that:

- Every RAG-red state and every breached threshold has an **assigned owner** (a person or team, not a role placeholder) and a **documented next action** visible on the widget itself.
- High-severity, unacknowledged findings (security, threat-model, release-blocking) auto-notify the owning channel/ticket system rather than waiting to be noticed on next dashboard open.
- Weekly/bi-weekly and quarterly review cadences open on the **Engineering Discipline** view first, per the original Operational Indicators doc's instruction — this PRD keeps that requirement and extends it to all perspectives: no review opens on a flow-only view.
- Track "reporting without behavior change" directly: month-on-month movement of the underlying practice (evidence completeness, PR-time coverage, escaped defects), not just dashboard adoption/usage counts.

---

## 10. Data model (unchanged, reference only)

The TDD's core entity list (`users`, `projects`, `dashboards`, `dashboard_versions`, `widgets`, `templates`, `connector_instances`, `normalized_artifacts`, `rules`, `rule_results`, `artifact_waivers`, `audit_logs`) is sound and carries forward as-is into the TDD phase. No changes proposed here beyond what §8 (RBAC) implies for the schema — a `project_access` or equivalent table is now in scope for v1, not deferred.

---

## 11. Success metrics

Borrowing the industry-standard framing (DORA's four keys: deployment frequency, lead time for changes, change failure rate, time to restore) as shared vocabulary layered on top of the existing metric set, so stakeholders outside this program can still read the dashboards:

| Metric | Direction | Source perspective |
|---|---|---|
| Definition of Ready completeness before dev starts | Up | Engineering Discipline |
| Definition of Done completeness at sign-off | Up | Engineering Discipline |
| Scoped-down artifacts with recorded, defensible rationale | Up (as share of all omissions) | Engineering Discipline |
| PR-time coverage / early-layer test share | Up | Execution Health |
| Late-stage and post-deploy defect discovery | Down | Execution Health / Release Confidence |
| Escaped, customer-facing defects | Down | Release & Quality Confidence |
| Change failure rate, deployment frequency, lead time, MTTR (DORA) | Improving | Delivery Control / Release Confidence |
| Dashboard-adoption vs. actual behavior-metric movement | Behavior metrics must move, not just adoption | Executive Signal |

---

## 12. Phased rollout (corrected)

Phase 0 is unchanged and correctly unconditional — teams work to the current Definition of Ready/Done today, independent of the platform. Phases below are re-sequenced so the evidence view isn't last:

1. **Phase 0** — current DoR/DoD discipline, no platform dependency (ongoing now).
2. **Phase 1** — connectors for Jira, Confluence, Xray, GitHub/Bitbucket, CI. RBAC/project-scoped access ships in this phase, not later.
3. **Phase 2** — **Engineering Discipline & Feature Readiness** launches first among the six perspectives. This is the corrected sequencing: the prior plan launched execution health, delivery control, and engineering discipline "together," which in practice usually means flow ships first because it's easier.
4. **Phase 3** — Execution Health + Delivery Control (including Operational Indicators).
5. **Phase 4** — Release & Quality Confidence.
6. **Phase 5** — Portfolio Quality + Executive Signal, with trend analytics.
7. **Phase 6** — AI summarization, clustering, proactive anomaly detection.

---

## 13. Risks (elevated from the TDD, RBAC reclassified)

| Risk | Prior classification | This PRD's classification | Mitigation |
|---|---|---|---|
| No RBAC / over-broad visibility | "Start internal-only, add later" | **Launch-blocking** | Project-scoped access ships in Phase 1 |
| Flow metrics mistaken for evidence | High | High (unchanged) | Structural link + banner, not just documentation |
| Cross-team benchmarking recreating a feature-factory incentive | Noted only if added later | Carried forward unchanged — never ship benchmarking without paired quality signals | Pair with escaped-defect and evidence-completeness signals always |
| Reporting without behavior change | Medium | Medium, now has a tracked counter-metric (§9, §11) | Actionability requirements |
| Connector fragility / data inconsistency | High | High (unchanged) | Canonical model, versioned connectors |
| AI trust issues | Medium | Medium (unchanged) | Human acceptance recorded, drill-down always available |

---

## 14. Open decisions for the TDD phase

- Exact RBAC model: project-level roles vs. team-inherited SSO groups.
- Whether Release & Quality Confidence needs its own connector set or fully reuses Execution Health's.
- Analytics store: stay on Postgres for v1 or introduce a dedicated analytical store (DuckDB/ClickHouse) — TDD already flags this, still open.
- Ownership/paging integration target (PagerDuty vs. Jira Service Management vs. Slack) for the actionability requirements in §9.

---

## 15. Design rationale — what this borrows from mature engineering orgs

- **Evidence over assertion, gates owned by humans, dashboards report on gates rather than becoming one** — this is the SRE/error-budget pattern popularized by Google: a dashboard is a decision aid, the human on call (here, the ETL/PM) still owns the call.
- **DORA's four keys as shared vocabulary** — using a widely-recognized, externally-benchmarked metric set alongside Backbase-specific ones means any new leader reading the Executive Signal view doesn't need onboarding to interpret it.
- **Curated templates plus a self-serve builder, not one or the other** — mirrors the internal-tooling pattern common at large engineering orgs (a small set of opinionated "golden" dashboards for governance, with a general-purpose builder underneath for teams that need something the golden set doesn't cover).
- **"A stale or missing signal must never render as healthy"** — a direct corollary of blameless, evidence-driven operational practice: silence is treated as an unknown, not a pass.
