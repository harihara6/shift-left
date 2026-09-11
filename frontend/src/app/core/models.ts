/** Mirrors the FastAPI schemas in backend/app/schemas. */

export type Rag = 'good' | 'watch' | 'poor' | 'neutral' | 'missing';

/** A status always travels with its reasons. It is never reduced to a score. */
export interface RagState {
  rag: Rag;
  label: string;
  glyph: string;
  reasons: string[];
}

export interface ConnectorFreshness {
  key: string;
  name: string;
  state: string;
  last_successful_sync: string | null;
  age_minutes: number | null;
  threshold_minutes: number;
  stale: boolean;
  missing: boolean;
}

export interface Freshness {
  stale: boolean;
  oldest_sync: string | null;
  note: string;
  connectors: ConnectorFreshness[];
}

export interface DrillDown {
  label: string;
  url: string;
  system: string;
}

export interface WidgetGuide {
  widget: string;
  decision: string;
  source: string;
  fetch: string;
  tagging: string;
}

export interface Period {
  key: string;
  label: string;
  granularity: string;
  start: string;
  end: string;
  weeks: number;
  complete: boolean;
  window_label: string;
  has_data: boolean;
}

export interface Comparison {
  current: Period;
  baseline: Period;
  granularity: string;
  preset: string;
  comparable_lengths: boolean;
  caveat: string;
  covered_periods: string[];
  missing_periods: string[];
  aggregated: boolean;
}

export interface FilterOptions {
  granularities: { key: string; label: string }[];
  presets: { key: string; label: string }[];
  periods: Record<string, Period[]>;
  data_through: string;
}

/** What the filter currently asks for. `period`/`baseline` only apply to the custom preset. */
export interface PeriodSelection {
  granularity: string;
  preset: string;
  period?: string;
  baseline?: string;
}

export interface GlanceRow {
  row: string;
  current: string;
  baseline: string;
  status: RagState;
  drill: DrillDown | null;
}

export interface Tile {
  label: string;
  value: string;
  note: string;
  status: RagState | null;
  drill: DrillDown | null;
}

export interface Series {
  name: string;
  color: string;
  data: number[];
}

export interface ChartSpec {
  key: string;
  title: string;
  kind: 'bar' | 'line';
  x_labels: string[];
  series: Series[];
  caption: string;
}

export interface DeckSection {
  key: string;
  title: string;
  scope: string;
  tiles: Tile[];
  charts: ChartSpec[];
}

export interface EvidenceLink {
  label: string;
  perspective: string;
  project_id: string;
  note: string;
}

export interface TeamInsights {
  project_id: string;
  project_label: string;
  comparison: Comparison;
  window: string;
  comparison_caveat: string;
  freshness: Freshness;
  evidence_link: EvidenceLink;
  glance: GlanceRow[];
  glance_note: string;
  sections: DeckSection[];
  guide: WidgetGuide[];
  notes: string[];
}

/* --- Feature Readiness (Engineering Discipline) --- */

export interface ArtifactRow {
  key: string;
  name: string;
  accountable: string;
  gate: string;
  source: string;
  status: RagState;
  status_label: string;
  note: string;
  counts_toward_gate: boolean;
  drill: DrillDown | null;
  status_only: boolean;
}

export interface Completeness {
  done: number;
  total: number;
  percent: number;
  label: string;
  status: RagState;
}

export interface AiDraft {
  text: string;
  drawn_from: string;
  accepted_by: string | null;
  accepted_at: string | null;
  accepted: boolean;
  note: string;
}

export interface FeatureRow {
  key: string;
  name: string;
  tier: string;
  gate: string;
  owner: string;
  next_action: string;
  action_age: string;
  status: RagState;
  reason: string;
  ready: Completeness;
  done: Completeness;
  missing: string[];
  artifacts: ArtifactRow[];
  ai: AiDraft | null;
  drill: DrillDown | null;
  gate_note: string;
}

export interface Waiver {
  artifact: string;
  feature_key: string;
  tier: string;
  owner: string;
  waived_at: string;
  rationale: string;
  flagged: boolean;
  flag_note: string;
}

export interface ActionRecord {
  id: number;
  signal: string;
  next_action: string;
  owner: string;
  age: string;
  status: string;
  status_label: string;
  severity: RagState;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
}

export interface FlowLink {
  label: string;
  perspective: string;
  project_id: string;
  note: string;
}

export interface FeatureReadiness {
  project_id: string;
  project_label: string;
  release: string;
  evidence_of_record: boolean;
  subtitle: string;
  freshness: Freshness;
  flow_link: FlowLink;
  tiles: Tile[];
  features: FeatureRow[];
  waivers: Waiver[];
  waiver_note: string;
  actions: ActionRecord[];
  guide: WidgetGuide[];
}

export interface AccessGrant {
  id: number;
  principal: string;
  role: string;
  via: string;
  granted_by: string;
}

export interface ProjectSummary {
  id: string;
  key: string;
  name: string;
  owner: string;
  created_on: string;
  dashboards: number;
  archived: boolean;
}

export interface ProjectDetail extends ProjectSummary {
  access: AccessGrant[];
}

export interface WidgetBinding {
  id: number;
  name: string;
  connector_key: string;
  connector_name: string;
  query: string;
  refresh_interval: string;
  drill_template: string;
  last_sync: string | null;
  stale: boolean;
  guide_key: string | null;
}

export interface ProjectTemplate {
  id: number | null;
  template_key: string;
  name: string;
  perspective: string;
  enabled: boolean;
  copied_from_version: number | null;
  copied_at: string | null;
  widgets: WidgetBinding[];
}

export interface QueryPreview {
  connector_key: string;
  query: string;
  ok: boolean;
  rows: Record<string, unknown>[];
  row_count: number;
  note: string;
  stale: boolean;
}

export interface ConnectorSummary {
  key: string;
  name: string;
  category: string;
  state: string;
  state_label: string;
  last_successful_sync: string | null;
  sync_label: string;
  instances: number;
  stale: boolean;
}

export interface ConnectorField {
  key: string;
  label: string;
  help: string;
  type: string;
  value: string | null;
  placeholder: string;
}

export interface ConnectorDetail extends ConnectorSummary {
  description: string;
  auth_methods: { label: string; recommended: boolean }[];
  selected_auth: string | null;
  fields: ConnectorField[];
  scopes: string;
  rate_limits: string;
  staleness_minutes: number;
  status_only: boolean;
}

export interface ConnectorTestResult {
  ok: boolean;
  message: string;
  capabilities: string[];
  filters: string[];
  checked_at: string;
}

export interface AccessModelEntry {
  title: string;
  detail: string;
}

/** Who the API says is calling - in production, whoever the SSO proxy authenticated. */
export interface WhoAmI {
  email: string;
  groups: string[];
  platform_admin: boolean;
  platform_admin_count: number;
}

export interface PerspectiveGuide {
  perspective: string;
  title: string;
  subtitle: string;
  audience: string[];
  widgets: (WidgetGuide & { widget_key: string })[];
  footnote: string;
}

/* --- Guided onboarding ------------------------------------------------------------------ */

/** One thing a source returned. `url` is what makes it checkable rather than claimed. */
export interface OnboardingCandidate {
  id: string;
  connector_key: string;
  slot: string;
  ref: string;
  title: string;
  url: string;
  detail: Record<string, string>;
  matched_on: string[];
}

export interface OnboardingSource {
  connector_key: string;
  connector_name: string;
  available: boolean;
  state: string;
  note: string;
  candidates: OnboardingCandidate[];
}

/** A resolved slot always travels with its evidence — the number is never shown alone. */
export interface OnboardingSlot {
  slot: string;
  candidate: OnboardingCandidate | null;
  confidence: number;
  rationale: string;
}

export interface OnboardingBinding {
  template_key: string;
  widget_name: string;
  connector_key: string;
  position: number;
  catalog_query: string;
  query: string;
  filled_slots: string[];
  unresolved_slots: string[];
  leftovers: string[];
  validated: boolean;
  row_count: number;
  note: string;
  /** Bound to something discovery actually found. */
  ready: boolean;
  /** Carried from the template unchanged — it names no team-specific value. */
  generic: boolean;
}

export interface OnboardingTemplate {
  template_key: string;
  name: string;
  perspective: string;
  propose_enabled: boolean;
  reason: string;
  bindings: OnboardingBinding[];
}

/** A proposal. Nothing in it exists until a named person accepts it. */
export interface OnboardingDraft {
  id: number;
  hint: string;
  status: string;
  /** 'claude' or 'name-match' — how the assignment was arrived at. */
  mode: string;
  note: string;
  discovery_available: boolean;
  caveats: string[];
  project_name: string;
  project_key: string;
  owner: string;
  sources: OnboardingSource[];
  slots: OnboardingSlot[];
  templates: OnboardingTemplate[];
  accepted_by: string | null;
  accepted_at: string | null;
  project_id: string | null;
}

export interface OnboardingAccept {
  key: string;
  name: string;
  owner: string;
  templates: string[];
  bindings: { template_key: string; widget_name: string; query: string }[];
}

export interface OnboardingResult {
  project: ProjectDetail;
  templates_enabled: string[];
  bindings_applied: number;
  bindings_left_empty: number;
  accepted_by: string;
  accepted_at: string;
  note: string;
}

/** Shift-left Rollout. Mirrors backend/app/schemas/rollout.py. */
export interface RolloutCriterion {
  label: string;
  /** Null when the data to judge it is absent - never treated as met. */
  met: boolean | null;
  status: RagState;
  evidence: string;
}

export interface RolloutStage {
  index: number;
  key: string;
  label: string;
  behaviour: string;
  state: 'done' | 'current' | 'ahead';
  criteria: RolloutCriterion[];
}

export interface RolloutSurface {
  key: string;
  name: string;
  system: string;
  gating: boolean;
  mode: 'off' | 'live' | 'warn' | 'block';
  mode_label: string;
  coverage: string;
  last_event: string;
  events: string;
  status: RagState;
  drill: DrillDown | null;
}

export interface RolloutDetector {
  key: string;
  name: string;
  source: string;
  method: string;
  audited: number;
  correct: number;
  false_missing: number;
  false_present: number;
  accuracy: number;
  note: string;
  status: RagState;
  status_only: boolean;
  drill: DrillDown | null;
}

export interface RolloutBoard {
  project_id: string;
  project_label: string;
  subtitle: string;
  stage: number;
  stage_label: string;
  stage_since: string;
  policy_version: string;
  policy_drill: DrillDown | null;
  audit_note: string;
  freshness: Freshness;
  evidence_link: EvidenceLink;
  tiles: Tile[];
  stages: RolloutStage[];
  can_advance: boolean;
  advance_blockers: string[];
  signoff: { by: string | null; at: string | null };
  surfaces: RolloutSurface[];
  detectors: RolloutDetector[];
  charts: ChartSpec[];
  guide: WidgetGuide[];
}

// --- Feature Kickoff (backend/app/schemas/kickoff.py) ---------------------------------------------

export interface KickoffLink {
  label: string;
  url: string;
}

export interface KickoffQuote {
  text: string;
  section: string;
}

export interface PrdPage {
  page_id: string;
  title: string;
  space: string;
  url: string;
  version: number;
  updated: string;
  author: string;
  own_project: boolean;
}

export interface PrdList {
  pages: PrdPage[];
  note: string;
  /** False when the live source can't be read; `note` says why. */
  available: boolean;
}

export interface KickoffConnection {
  key: string;
  name: string;
  direction: 'read' | 'write';
  /** 'configured' is from configuration alone: nothing is called to check it. */
  state: 'example' | 'configured' | 'not_configured' | 'not_built' | 'dry_run';
  note: string;
}

export interface KickoffConnections {
  sources: 'fixtures' | 'live';
  write_mode: 'dry-run' | 'live';
  connections: KickoffConnection[];
}

export interface ModelProvider {
  key: string;
  name: string;
  available: boolean;
  note: string;
  models: { id: string; display_name: string }[];
  default_model: string;
}

export interface ModelOptions {
  providers: ModelProvider[];
  default_provider: string;
}

export interface KickoffFact {
  key: string;
  label: string;
  values: string[];
  value_labels: string[];
  /** 'stated' (quoted from the PRD), 'not_stated', or 'confirmed' (set by a person). */
  status: string;
  quotes: KickoffQuote[];
  confirmed_by: string | null;
  /** Empty for free-text facts. */
  allowed: { value: string; label: string }[];
}

export type KickoffOutcome = 'applies' | 'not_applicable' | 'undetermined';

export interface KickoffAction {
  key: string;
  label: string;
  group: string;
  group_label: string;
  target: string;
  description: string;
  outcome: KickoffOutcome;
  outcome_label: string;
  reason: string;
  quotes: KickoffQuote[];
  question: string;
  recommended: boolean;
  selected: boolean;
  skip_reason: string;
  skip_flagged: boolean;
}

export interface KickoffDrawnFrom {
  kind: string;
  text: string;
  url: string;
  section: string;
}

export interface KickoffSuggestion {
  key: string;
  label: string;
  why: string;
  target: string;
  source: 'context' | 'check';
  kind: string;
  decision: 'pending' | 'accepted' | 'dismissed';
  drawn_from: KickoffDrawnFrom[];
}

export type FindingStatus = 'ok' | 'gap' | 'blocker' | 'not_checked';

export interface KickoffFinding {
  id: string;
  status: FindingStatus;
  title: string;
  detail: string;
  link: KickoffLink | null;
  quote: KickoffQuote | null;
}

export interface KickoffCheck {
  key: string;
  label: string;
  note: string;
  findings: KickoffFinding[];
}

export interface KickoffPlanItem {
  id: string;
  group: string;
  kind: string;
  title: string;
  detail: string;
  project: string;
  labels: string[];
  drawn_from: KickoffDrawnFrom[];
  diff: {
    op: 'add' | 'change';
    field?: string;
    label?: string;
    row?: string;
    before?: string[];
    after?: string[];
    fields?: Record<string, string>;
  } | null;
  included: boolean;
}

export interface KickoffCoverage {
  artifact: string;
  name: string;
  gate: string;
  state: 'covered' | 'waiver_draft' | 'not_applicable' | 'not_covered';
  item_id: string | null;
  note: string;
}

export interface KickoffPlan {
  items: KickoffPlanItem[];
  coverage: KickoffCoverage[];
  notes: string[];
  catalog_version: number;
  /** The product index isn't in Confluence: its version is what it states, or a content hash. */
  index_version: string;
}

export type KickoffResultStatus =
  | 'dry_run' | 'skipped' | 'created' | 'updated' | 'exists' | 'handoff' | 'failed';

export interface KickoffResult {
  item_id: string;
  group: string;
  title: string;
  status: KickoffResultStatus;
  message: string;
  link: KickoffLink | null;
}

export interface Kickoff {
  id: number;
  project_id: string;
  status: 'context' | 'planned' | 'applying' | 'partial' | 'applied';
  page: PrdPage;
  provider: string;
  model: string;
  reader: string;
  drafted_by: string;
  note: string;
  source_note: string;
  source_mode: 'fixtures' | 'live';
  write_mode: 'dry-run' | 'live';
  facts: KickoffFact[];
  tier: { tier: string; reason: string; undetermined: boolean; quotes: KickoffQuote[] };
  actions: KickoffAction[];
  suggestions: KickoffSuggestion[];
  checks: KickoffCheck[];
  headline: RagState | null;
  checked_at: string | null;
  plan: KickoffPlan | null;
  approved_by: string | null;
  approved_at: string | null;
  results: KickoffResult[];
  created_at: string | null;
}

export interface KickoffSummary {
  id: number;
  page_title: string;
  status: string;
  model: string;
  created_at: string | null;
  approved_by: string | null;
}

export interface KickoffChoice {
  key: string;
  selected: boolean;
  skip_reason: string;
}
