# ShiftLeft Quality & Delivery Observability — Design Handoff Kit

Prototype: `ShiftLeft Platform.dc.html` (+ `Chart.dc.html`)
Source of truth for requirements: the PRD and TDD in `/docs`.
Target implementation stack (per TDD §10): React + TypeScript front end, Java 21 / Spring Boot APIs, PostgreSQL, Redis, Kubernetes.

---

## 1. What is built

A working, clickable prototype of the whole platform: six dashboard perspectives, an evidence drill-down, a per-page metric/plumbing guide, and a full Settings area.

| Area | State | Notes for implementation |
|---|---|---|
| Feature Readiness (Engineering Discipline) | Complete | Primary screen. Table + slide-over evidence detail. |
| Developer & SDET Flow (Execution Health) | Complete | Tiles, detection trend, six SDLC stage panels. |
| Team Insights (Delivery Control) | Complete | Ported from the original HTML prototype, restyled; structure unchanged. |
| Release Readiness (Release & Quality Confidence) | Complete | Merged template — ship decision, tiles, trend, blockers. |
| Portfolio & Programme | Roll-up grid only | Deliberately thin; expand only if the programme review needs more. |
| Quality Trajectory (Executive Signal) | Complete | DORA framing + counter-metric panel. |
| Info modal (per page, per widget) | Complete | Audience, decision, source, fetch query, source-tagging convention. |
| Settings → Projects | Complete | Project CRUD affordances, template enable/disable, per-widget query binding, access grants. |
| Settings → Connectors | Complete | 16 connectors, each with its own auth model and field set. |
| Settings → Access & SSO | Complete | Written positioning of the authz model. |
| Not built | — | Dashboard builder canvas (drag/drop widget layout), audit-log browser, template version history, notification preferences. |

## 2. Design decisions (and why)

1. **Evidence outranks flow, structurally.** Feature Readiness is the first nav item, is the only screen with an "Evidence of record" badge, and is where "Open review" always lands. Flow screens (Execution Health, Team Insights) carry a persistent banner and a cross-link button into the evidence record. The rule from PRD §4.1 is enforced by layout and navigation, not by documentation.
2. **RAG always resolves to a list, never a score.** Red states render the literal missing artifacts ("Why this is red — 2 required artifacts absent"). No weighted composite appears anywhere in the UI. Implement `rule_results` so the reason list is a first-class field, not derived at render time.
3. **Missing is not green.** Absent data renders as `Missing`; a stale connector renders `Stale` in amber and forces the ship decision out of green. The `stalenessDemo` prop exists to demo this path.
4. **Scoped-out ≠ passed.** Waived artifacts are excluded from the denominator (so the percentage is honest) and listed separately with owner, timestamp and rationale. Rationales on the deny-list ("capacity pressure") render flagged in red.
5. **Two-level information architecture in the guide.** Page-level info button, but content is organised **per widget** inside it — the page level exists only to group. Each widget entry answers four fixed questions: decision supported / where it comes from / how it is fetched / how to tag it at source. Keep this four-field shape when adding widgets.
6. **Audience described as situations, not roles.** "Someone who wants a weekly update on how a team is moving" rather than "Engineering Manager". Titles change; the decision does not.
7. **Dark rail, light canvas.** The near-black sidebar is a constant anchor while the content area stays high-contrast for dense data. One accent (#3355FF) reserved for interaction and drill-down; status colours are never used decoratively.
8. **Monospace for every number.** JetBrains Mono on all metrics, IDs, queries and timestamps; Instrument Sans for prose. Digits align in columns, and queries read as code.
9. **Access is project-scoped, never per widget.** Deliberate simplification: a widget is exactly as visible as its project. Small enough to reason about during an incident.
10. **Secrets are write-only in the UI.** Credentials show as vault placeholders with a Rotate action; there is no reveal affordance to build.

## 3. Visual system

**Type** — Instrument Sans 400/500/600/700 (UI), JetBrains Mono 400/500/600 (numerics, IDs, queries). Both from Google Fonts.

Scale: page title 22/600, section 15–16/600, card title 13/600, body 12.5/1.6, meta 11–11.5, uppercase label 10–10.5 with 0.06–0.09em tracking.

**Colour**

| Token | Hex | Use |
|---|---|---|
| canvas | #F6F6F4 | app background |
| surface | #FFFFFF | cards, header, panels |
| surface-sunken | #FBFBF9 | table headers, nested config blocks |
| rail | #121316 | sidebar, inverted panels |
| rail-text | #9DA0A8 | sidebar labels |
| rail-active | #22252B | active nav row |
| border | #E7E6E1 | card borders |
| border-soft | #EFEEEA / #F2F1ED / #F4F3EF | internal dividers |
| ink | #16171B | primary text |
| ink-2 | #33353B | body text |
| muted | #6B6E76 | secondary text |
| faint | #9A9CA3 | meta text |
| accent | #3355FF (hover #2A45CC, bg #EDF0FF, border #D5DCFF) | interaction, drill-down, AI |
| good | #147A4B on #E7F4ED | |
| watch | #A66A00 on #FBF1DE | |
| poor | #C2352B on #FBEAE7 | |
| neutral | #8A8D95 on #F1F0EC | scoped-out / disabled |
| tier: new capability | #7A3BC4 on #F2EBFB | |

**Geometry** — radii 6 (chips) / 7–8 (buttons, inputs) / 10 (nested cards) / 12 (cards) / 14 (modal) / 99 (dots, toggles). Spacing 4/6/8/10/12/16/20/22/28. Card padding 14–18. Grid gaps 12 (tiles) / 16 (sections).

**Patterns** — metric tile, RAG dot + label, status pill, evidence progress bar, data table as CSS grid with `minmax(0, Nfr)` tracks (never fixed px — it clips), slide-over panel (660px, scrim rgba(18,19,22,.42)), centred modal (920px max, 86vh), toggle switch, connector list item, key/value config row.

**Charts** — one component, two modes (grouped bars, multi-series line), 640×220 viewBox, 5 horizontal gridlines at #ECEBE7, y-labels in mono, 2px strokes with 2.8r dots, 2px bar radius. Every chart carries a caption naming the source and both axes.

## 4. Screen inventory

1. **Feature Readiness** — 4 summary tiles (DoR, DoD, cleared at gate, scoped-out) → feature table (feature, risk tier, ready evidence bar, done evidence bar, status + reason, chevron) → slide-over: why-red block, 11-row evidence checklist (artifact, accountable, source, status, drill link), AI draft card requiring recorded acceptance, owner + next action, linked flow record. Side panels: waivers list, open actions with acknowledge.
2. **Developer & SDET Flow** — flow banner, 4 headline tiles, detection line chart, six stage cards (Plan → Maintain), three signals each.
3. **Team Insights** — flow banner, Q2/Q3 glance table, four sections (Epics, Stories, MAINT, PRs) each with 4 tiles + 2 charts.
4. **Release Readiness** — ship decision card with literal blocking reasons, test-execution trend, 8 tiles, blocker table.
5. **Portfolio & Programme** — team × signal heatmap grid.
6. **Quality Trajectory** — 4 tiles incl. DORA keys, five-quarter trend, inverted counter-metric panel.
7. **Settings** — Projects / Connectors / Access & SSO.

Cross-navigation to implement: flow banner → evidence record; slide-over → flow record; "Open review" → Feature Readiness (per TDD §8, reviews never open on a flow view).

## 5. Data the UI expects

Aligned to the TDD §9 entity list. Shapes used by the prototype:

```ts
type Status = 'present' | 'drafted' | 'missing' | 'stale' | 'waived';
type Rag = 'good' | 'watch' | 'poor';
type Tier = 'New capability' | 'Major change' | 'Minor change' | 'Config / copy';

interface ArtifactDef { key: string; name: string; accountable: string; gate: 'Ready'|'Done'|'Both'; source: string }

interface FeatureEvidence {
  id: string; name: string; tier: Tier; gate: 'Ready gate'|'Done gate'; rag: Rag;
  artifacts: { key: string; status: Status; note?: string; sourceUrl?: string }[];
  owner: string; nextAction: string; actionAgeDays: number;
  aiDraft?: { text: string; drawnFrom: string; acceptedBy?: string; acceptedAt?: string };
}
// Ready/Done completeness = present|stale artifacts for that gate ÷ non-waived artifacts for that gate.

interface Waiver { artifact: string; featureId: string; tier: Tier; owner: string; at: string; rationale: string; flagged: boolean }
interface ActionRecord { signalId: string; dashboardId: string; owner: string; nextAction: string;
  status: 'open'|'acknowledged'|'resolved'; severity: Rag; createdAt: string; acknowledgedAt?: string; resolvedAt?: string }
interface WidgetBinding { widget: string; connectorId: string; query: string; refreshInterval: string; drillTemplate: string; lastSync: string }
```

The 11 canonical artifacts (order matters — it is the checklist order): requirements incl. visual design; acceptance criteria incl. NFRs; test plan incl. NFR testing; HLD; LLD per platform; threat model; traceability matrix; test evidence; performance; accessibility WCAG 2.2 AA; AI-first / T-shaped evidence.

## 6. Connectors

Each connector declares its own auth model and field set — the config form is data-driven, not one shared form. Summary of what the prototype encodes:

- **Jira** — OAuth 2.0 (3LO) app / API token + service account / DC PAT. Site URL, project keys, custom-field map (Risk tier, Detection stage). Scopes read:jira-work, read:jira-user.
- **Confluence** — same Atlassian auth. Spaces in scope, artifact→label map (sl-requirements, sl-testplan, sl-hld, sl-lld, sl-threatmodel, sl-performance, sl-accessibility).
- **Xray** — Cloud: API key (client ID + client secret) exchanged for a bearer token that expires after 24h. Server/DC: Jira PAT instead. Rate limited (300/5min Standard, 1000/5min Enterprise).
- **GitHub** — App installation (installation ID + private key + webhook secret) or fine-grained PAT. Scopes contents/pull_requests/checks/actions/deployments read.
- **CI (GitHub Actions)** — shares the GitHub installation; workflow allow-list + evidence artifact names.
- **Bitbucket / Jenkins** — alternates, disabled by default.
- **SonarQube** — server URL + user token, project keys, branch strategy.
- **LinearB** — API key + team IDs mapped to projects.
- **JSM** — shares Jira; service-desk project, Caused-by-deployment field, alert queue.
- **Slack** — bot token, default channel, severity filter.
- **Sentry** — org slug + internal integration token, projects, release naming rule.
- **PagerDuty / Datadog** — declared, not configured in v1.
- **Figma** — OAuth or PAT, file keys, frame naming rule (frame contains the Jira key).
- **Security scanners** — CodeQL + Snyk, severity floor, status-only content policy.

Every connector instance exposes last-successful-sync; past threshold it renders a warning and cannot contribute to green.

## 7. Source tagging conventions the UI assumes

These are the conventions surfaced in every info modal. Confirm with the teams before build — they were proposed here, not observed.

- Jira issue label `shiftleft-tracked` + `fixVersion = Release 2026.3` to appear at all.
- Jira fields: Risk tier, Detection stage (pr/nightly/staging/production), Found-in build, Caused-by deployment, Team.
- Jira labels: `release-blocker`, `fix` (for the regression-test check), `tech` (technical stories).
- Confluence page labels per artifact (list above), linked to the Jira issue.
- Test suites tagged `@L1 @L2 @L3 @L4`; untagged defaults to L3 and skews the pyramid.
- CI artifact names `accessibility-report`, `performance-report`, `junit-results`.
- Figma frame names contain the Jira key.

## 8. Implementation notes for an agentic build

- Build the six perspectives as **routes**, one shell (rail + header + scroll body). The header owns title, perspective label, filters, info button.
- The info-guide content is **content, not chrome** — store it beside each widget definition so a new widget cannot ship without its four guide fields. That constraint is the point.
- Tables must use `grid-template-columns: minmax(0, Nfr) …`; fixed px minimums clip at laptop widths (this bit the prototype twice).
- Scrollable flex columns need `flex: 0 0 auto` on children, or the children compress instead of the container scrolling.
- Slide-over and modal both close on scrim click and Escape.
- Charts: one component, spec-driven (legend, grid, bars, lines, dots, xlabels, caption). Geometry computed outside the render.
- Accessibility: this tool reports on WCAG 2.2 AA compliance, so it must meet it. Current gaps to close in the real build: focus-visible rings, keyboard-reachable table rows (they are div-based here), aria-live on the acknowledge action, and colour-plus-shape for every RAG state (dots are currently colour-only — add a glyph).

## 9. Files

- `ShiftLeft Platform.dc.html` — the full prototype: markup, all data, all interaction logic.
- `Chart.dc.html` — the chart renderer.
- `docs/PRD-*.md`, `docs/TDD-*.md` — the requirement sources.
- `docs/original-prototype.html` — the earlier HTML prototype Team Insights was ported from.
