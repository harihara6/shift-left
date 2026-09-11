import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { Api } from '../../core/api';
import { Refusal, errorMessage, refusal, writeRefusal } from '../../core/errors';
import {
  FindingStatus,
  Kickoff,
  KickoffAction,
  KickoffConnection,
  KickoffConnections,
  KickoffFact,
  KickoffPlanItem,
  KickoffResultStatus,
  KickoffSuggestion,
  KickoffSummary,
  ModelOptions,
  ModelProvider,
  PerspectiveGuide,
  PrdList,
} from '../../core/models';
import { GuideModal } from '../../ui/guide-modal';
import { RagBadge } from '../../ui/rag-badge';

type Step = 'source' | 'context' | 'actions' | 'checks' | 'plan' | 'create';

interface Tone {
  glyph: string;
  label: string;
  tone: string;
}

/** Plan groups, in the order the plan is read. */
const GROUPS: { key: string; label: string }[] = [
  { key: 'jira', label: 'Jira backlog' },
  { key: 'xray', label: 'Xray' },
  { key: 'confluence', label: 'Confluence pages' },
  { key: 'software_catalog', label: 'Software catalog' },
  { key: 'product_index', label: 'Product index' },
  { key: 'waivers', label: 'Waiver drafts' },
];

/**
 * Feature Kickoff: take a PRD from Confluence to a checked, tagged plan, and confirm it.
 *
 * Nothing on this page decides anything. What applies, why, what the checks found and what the
 * plan contains all arrive from the API with their reasons; the page shows them and sends the
 * person's choices back. Every write is authorized server-side, and the one that creates things
 * is the last step, recorded against whoever confirms it.
 */
@Component({
  selector: 'sl-kickoff',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule, GuideModal, RagBadge],
  templateUrl: './kickoff.html',
  styleUrls: ['./kickoff.css', './kickoff-plan.css'],
})
export class KickoffPage {
  private readonly api = inject(Api);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly projectId = input.required<string>();

  readonly steps: { id: Step; label: string }[] = [
    { id: 'source', label: 'PRD' },
    { id: 'context', label: 'What it says' },
    { id: 'actions', label: 'What to do' },
    { id: 'checks', label: 'Checks' },
    { id: 'plan', label: 'Plan' },
    { id: 'create', label: 'Confirm' },
  ];
  readonly groups = GROUPS;

  readonly step = signal<Step>('source');
  readonly busy = signal(false);
  readonly refusal = signal<Refusal | null>(null);
  /** Announced politely, so every result of a write is heard, not only seen. */
  readonly announcement = signal('');

  // Step 1 ------------------------------------------------------------------------------------
  readonly prds = signal<PrdList | null>(null);
  readonly query = signal('');
  readonly pageId = signal('');
  readonly models = signal<ModelOptions | null>(null);
  readonly providerKey = signal('');
  readonly model = signal('');
  readonly recent = signal<KickoffSummary[]>([]);
  /** Where reads and writes go. Shown before anything runs, so nobody mistakes examples for live. */
  readonly connections = signal<KickoffConnections | null>(null);

  readonly provider = computed<ModelProvider | null>(
    () => this.models()?.providers.find((p) => p.key === this.providerKey()) ?? null,
  );

  // The session --------------------------------------------------------------------------------
  readonly session = signal<Kickoff | null>(null);

  // Step 2: fact edits, keyed by fact. Absent means "as read".
  readonly editing = signal<string | null>(null);
  readonly draftValues = signal<string[]>([]);
  readonly draftText = signal('');

  // Step 3: the person's choices, keyed by action. Absent means "as recommended".
  readonly choices = signal<Record<string, { selected: boolean; reason: string }>>({});

  readonly openGuide = signal(false);
  readonly guide = signal<PerspectiveGuide | null>(null);

  readonly actionGroups = computed(() => {
    const actions = this.session()?.actions ?? [];
    const labels = [...new Set(actions.map((a) => a.group_label))];
    return labels.map((label) => ({ label, actions: actions.filter((a) => a.group_label === label) }));
  });
  readonly questions = computed(
    () => this.session()?.actions.filter((a) => a.outcome === 'undetermined' && a.question) ?? [],
  );
  readonly contextSuggestions = computed(
    () => this.session()?.suggestions.filter((s) => s.source === 'context') ?? [],
  );
  readonly checkSuggestions = computed(
    () => this.session()?.suggestions.filter((s) => s.source === 'check') ?? [],
  );
  readonly includedCount = computed(() => this.session()?.plan?.items.filter((i) => i.included).length ?? 0);
  /** Confirmed by a named person: the plan is frozen, whatever happened to its writes. */
  readonly confirmed = computed(() => ['applying', 'partial', 'applied'].includes(this.session()?.status ?? ''));
  readonly live = computed(() => (this.session()?.write_mode ?? this.connections()?.write_mode) === 'live');
  readonly failedCount = computed(() => this.session()?.results.filter((r) => r.status === 'failed').length ?? 0);
  readonly resultCounts = computed(() => {
    const counts = new Map<KickoffResultStatus, number>();
    for (const r of this.session()?.results ?? []) counts.set(r.status, (counts.get(r.status) ?? 0) + 1);
    return [...counts.entries()].map(([status, count]) => ({ tone: this.resultTone(status), count }));
  });

  constructor() {
    effect(() => {
      const id = this.projectId();
      // A project switch discards everything that belonged to the project you just left.
      untracked(() => this.reset(id));
    });
  }

  private reset(projectId: string): void {
    this.session.set(null);
    this.step.set('source');
    this.pageId.set('');
    this.query.set('');
    this.refusal.set(null);
    this.choices.set({});
    if (!projectId) return;
    this.loadPrds();
    this.api.kickoffConnections(projectId).subscribe({
      next: (c) => this.connections.set(c),
      error: () => this.connections.set(null),
    });
    this.api.kickoffModels(projectId).subscribe({
      next: (options) => {
        this.models.set(options);
        this.pickProvider(options.default_provider);
      },
      error: (err) => this.refusal.set(writeRefusal(err, 'The model list could not be loaded.')),
    });
    this.api.myKickoffs(projectId).subscribe({
      next: (rows) => this.recent.set(rows),
      error: () => this.recent.set([]),
    });
  }

  loadPrds(): void {
    this.api.kickoffPrds(this.projectId(), this.query().trim()).subscribe({
      next: (list) => {
        this.prds.set(list);
        if (!this.pageId() && list.pages[0]?.own_project) this.pageId.set(list.pages[0].page_id);
      },
      error: (err) => this.refusal.set(writeRefusal(err, 'PRD pages could not be listed.')),
    });
  }

  pickProvider(key: string): void {
    this.providerKey.set(key);
    const provider = this.models()?.providers.find((p) => p.key === key);
    this.model.set(provider?.default_model || provider?.models[0]?.id || '');
  }

  // --- Navigation --------------------------------------------------------------------------------

  canGo(step: Step): boolean {
    const s = this.session();
    if (step === 'source') return true;
    if (!s) return false;
    if (step === 'context' || step === 'actions') return true;
    return s.status !== 'context';
  }

  go(step: Step): void {
    if (this.canGo(step)) {
      this.refusal.set(null);
      this.show(step);
    }
  }

  /** A new step starts at its top, with focus on the stepper, so nobody lands mid-page. */
  private show(step: Step): void {
    this.step.set(step);
    afterNextRender(
      () => {
        const host = this.host.nativeElement;
        host.scrollIntoView({ block: 'start' });
        host.querySelector<HTMLElement>('.step[aria-current="step"]')?.focus({ preventScroll: true });
      },
      { injector: this.injector },
    );
  }

  // --- Step 1: read ------------------------------------------------------------------------------

  start(): void {
    if (!this.pageId() || !this.providerKey() || !this.model()) return;
    this.write(
      this.api.startKickoff(this.projectId(), {
        page_id: this.pageId(),
        provider: this.providerKey(),
        model: this.model(),
      }),
      (s) => {
        this.show('context');
        return `Read ${s.page.title}. ${s.facts.filter((f) => f.status === 'stated').length} facts found, each quoted.`;
      },
    );
  }

  resume(id: number): void {
    this.api.kickoff(this.projectId(), id).subscribe({
      next: (s) => {
        this.adopt(s);
        this.show(this.confirmed() ? 'create' : s.status === 'planned' ? 'plan' : 'context');
      },
      error: (err) => this.refusal.set(refusal(err, 'That kickoff could not be opened.')),
    });
  }

  // --- Step 2: facts -----------------------------------------------------------------------------

  edit(fact: KickoffFact): void {
    this.editing.set(fact.key);
    this.draftValues.set([...fact.values]);
    this.draftText.set(fact.values.join(', '));
  }

  toggleDraftValue(value: string): void {
    this.draftValues.update((values) =>
      values.includes(value) ? values.filter((v) => v !== value) : [...values, value],
    );
  }

  saveFact(fact: KickoffFact): void {
    const s = this.session();
    if (!s) return;
    const values = fact.allowed.length
      ? this.draftValues()
      : this.draftText().split(',').map((v) => v.trim()).filter(Boolean);
    this.write(this.api.updateKickoffFacts(this.projectId(), s.id, [{ key: fact.key, values }]), () => {
      this.editing.set(null);
      this.choices.set({});
      return `${fact.label} recorded as confirmed by you. Every rule was re-resolved.`;
    });
  }

  // --- Step 3: actions ---------------------------------------------------------------------------

  isSelected(action: KickoffAction): boolean {
    return this.choices()[action.key]?.selected ?? action.selected;
  }

  reasonFor(action: KickoffAction): string {
    return this.choices()[action.key]?.reason ?? action.skip_reason;
  }

  toggleAction(action: KickoffAction): void {
    const selected = !this.isSelected(action);
    this.choices.update((all) => ({ ...all, [action.key]: { selected, reason: this.reasonFor(action) } }));
  }

  setReason(action: KickoffAction, reason: string): void {
    this.choices.update((all) => ({
      ...all,
      [action.key]: { selected: this.isSelected(action), reason },
    }));
  }

  needsReason(action: KickoffAction): boolean {
    return action.recommended && !this.isSelected(action);
  }

  runChecks(): void {
    const s = this.session();
    if (!s) return;
    const choices = s.actions.map((a) => ({
      key: a.key,
      selected: this.isSelected(a),
      skip_reason: this.isSelected(a) ? '' : this.reasonFor(a).trim(),
    }));
    this.write(this.api.chooseKickoffActions(this.projectId(), s.id, choices), (next) => {
      this.choices.set({});
      this.show('checks');
      const count = next.checks.reduce((n, c) => n + c.findings.length, 0);
      return `Checks ran: ${count} finding(s). The plan is drafted and nothing has been written.`;
    });
  }

  // --- Suggestions and the plan ------------------------------------------------------------------

  decide(suggestion: KickoffSuggestion, decision: 'accepted' | 'dismissed' | 'pending'): void {
    const s = this.session();
    if (!s) return;
    this.write(
      this.api.updateKickoffPlan(this.projectId(), s.id, { decisions: { [suggestion.key]: decision } }),
      () =>
        decision === 'accepted'
          ? `Added: ${suggestion.label}.`
          : decision === 'dismissed'
            ? `Dismissed: ${suggestion.label}.`
            : `Undecided: ${suggestion.label}.`,
    );
  }

  toggleItem(item: KickoffPlanItem): void {
    const s = this.session();
    if (!s?.plan) return;
    const excluded = s.plan.items.filter((i) => (i.id === item.id ? i.included : !i.included)).map((i) => i.id);
    this.write(this.api.updateKickoffPlan(this.projectId(), s.id, { excluded }), () =>
      item.included ? `Left out: ${item.title}.` : `Included: ${item.title}.`,
    );
  }

  itemsIn(group: string): KickoffPlanItem[] {
    return this.session()?.plan?.items.filter((i) => i.group === group) ?? [];
  }

  includedIn(group: string): number {
    return this.itemsIn(group).filter((i) => i.included).length;
  }

  itemTitle(id: string | null): string {
    if (!id) return '—';
    return this.session()?.plan?.items.find((i) => i.id === id)?.title ?? id;
  }

  /** The confirmation, and the retry of a plan whose items partly failed: the same frozen plan. */
  apply(): void {
    const s = this.session();
    if (!s) return;
    const retry = s.status === 'partial';
    this.write(this.api.applyKickoff(this.projectId(), s.id), (next) => {
      this.api.myKickoffs(this.projectId()).subscribe({ next: (rows) => this.recent.set(rows) });
      const count = (...statuses: KickoffResultStatus[]) =>
        next.results.filter((r) => statuses.includes(r.status)).length;
      if (next.write_mode === 'dry-run') {
        return `Dry run confirmed by ${next.approved_by}: ${count('dry_run')} item(s) would be created, ${count('skipped')} left out. Nothing was written.`;
      }
      const summary =
        `${count('created', 'updated', 'exists')} done, ${count('handoff')} handed off, ` +
        `${count('failed')} failed, ${count('skipped')} left out.`;
      return `${retry ? 'Retried' : `Confirmed by ${next.approved_by}`}: ${summary}`;
    });
  }

  startOver(): void {
    this.reset(this.projectId());
  }

  showGuide(): void {
    if (this.guide()) {
      this.openGuide.set(true);
      return;
    }
    this.api.guide('kickoff').subscribe({
      next: (guide) => {
        this.guide.set(guide);
        this.openGuide.set(true);
      },
      error: (err) => this.refusal.set(refusal(err, 'The guide for this page could not be loaded.')),
    });
  }

  // --- Presentation (tone is always colour plus glyph) ---------------------------------------------

  outcomeTone(action: KickoffAction): Tone {
    if (action.outcome === 'applies') return { glyph: '✓', label: action.outcome_label, tone: 'good' };
    if (action.outcome === 'undetermined') return { glyph: '?', label: action.outcome_label, tone: 'watch' };
    return { glyph: '—', label: action.outcome_label, tone: 'neutral' };
  }

  findingTone(status: FindingStatus): Tone {
    switch (status) {
      case 'ok':
        return { glyph: '✓', label: 'OK', tone: 'good' };
      case 'gap':
        return { glyph: '!', label: 'Gap', tone: 'watch' };
      case 'blocker':
        return { glyph: '✕', label: 'Blocker', tone: 'poor' };
      default:
        return { glyph: '?', label: 'Not checked', tone: 'missing' };
    }
  }

  factTone(fact: KickoffFact): Tone {
    if (fact.status === 'confirmed') return { glyph: '✓', label: 'Confirmed by you', tone: 'good' };
    if (fact.status === 'stated') return { glyph: '“', label: 'Stated in the PRD', tone: 'neutral' };
    return { glyph: '?', label: 'Not in the PRD', tone: 'watch' };
  }

  coverageTone(state: string): Tone {
    if (state === 'covered') return { glyph: '✓', label: 'Covered', tone: 'good' };
    if (state === 'waiver_draft') return { glyph: '—', label: 'Waiver draft', tone: 'neutral' };
    if (state === 'not_applicable') return { glyph: '—', label: 'Not applicable', tone: 'neutral' };
    return { glyph: '?', label: 'Not covered', tone: 'missing' };
  }

  resultTone(status: KickoffResultStatus): Tone {
    switch (status) {
      case 'created':
        return { glyph: '✓', label: 'Created', tone: 'good' };
      case 'updated':
        return { glyph: '✓', label: 'Updated', tone: 'good' };
      case 'exists':
        return { glyph: '✓', label: 'Already there', tone: 'good' };
      case 'handoff':
        return { glyph: '↗', label: 'Handed off', tone: 'watch' };
      case 'failed':
        return { glyph: '✕', label: 'Failed', tone: 'poor' };
      case 'dry_run':
        return { glyph: '○', label: 'Dry run', tone: 'neutral' };
      default:
        return { glyph: '—', label: 'Left out', tone: 'neutral' };
    }
  }

  /** Configured is from configuration alone; it never claims a connection was tested. */
  connectionTone(c: KickoffConnection): Tone {
    switch (c.state) {
      case 'configured':
        return { glyph: '✓', label: 'Configured', tone: 'neutral' };
      case 'example':
        return { glyph: '!', label: 'Example data', tone: 'watch' };
      case 'dry_run':
        return { glyph: '○', label: 'Dry run', tone: 'watch' };
      case 'not_built':
        return { glyph: '?', label: 'Not built yet', tone: 'missing' };
      default:
        return { glyph: '?', label: 'Not configured', tone: 'missing' };
    }
  }

  modelNames(provider: ModelProvider): string {
    const names = provider.models.slice(0, 4).map((m) => m.display_name).join(', ');
    return provider.models.length > 4 ? `${names}…` : names;
  }

  /** The project's own Jira key: the plan's epic carries it. */
  projectKey(s: Kickoff): string {
    return s.plan?.items.find((i) => i.group === 'jira')?.project ?? 'this project';
  }

  diffFields(item: KickoffPlanItem): { key: string; value: string }[] {
    return Object.entries(item.diff?.fields ?? {}).map(([key, value]) => ({
      key: key.replace(/_/g, ' '),
      value,
    }));
  }

  // --- Writes ------------------------------------------------------------------------------------

  private adopt(s: Kickoff): void {
    this.session.set(s);
  }

  private write(call: Observable<Kickoff>, done: (s: Kickoff) => string): void {
    this.busy.set(true);
    this.refusal.set(null);
    call.subscribe({
      next: (s) => {
        this.adopt(s);
        this.busy.set(false);
        this.announcement.set(done(s));
      },
      error: (err) => {
        this.busy.set(false);
        // The API's refusal in the API's words, with its reasons as a list.
        const refused = writeRefusal(err, errorMessage(err, 'That step was refused.'));
        this.refusal.set(refused);
        this.announcement.set(refused.message);
      },
    });
  }
}
