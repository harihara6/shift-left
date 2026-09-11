import { DatePipe, DecimalPipe, NgTemplateOutlet } from '@angular/common';
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
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable } from 'rxjs';

import { Api } from '../../core/api';
import { Refusal, errorMessage, refusal, writeRefusal } from '../../core/errors';
import {
  ComplianceFramework,
  CustomCompliance,
  KickoffAnalysis,
  KickoffAnalysisSummary,
  KickoffCatalog,
  KickoffComplianceSuggestion,
  KickoffConnection,
  KickoffDoc,
  KickoffRepo,
  KickoffStatus,
  KickoffStepKey,
  PerspectiveGuide,
  ProviderCatalogEntry,
} from '../../core/models';
import { GuideModal } from '../../ui/guide-modal';
import { KickoffAnalysisStep } from './kickoff-analysis';

type RepoRole = 'repos' | 'dependencies';

interface Tone {
  glyph: string;
  label: string;
  tone: string;
}

/** What each step asks, in the order they're taken. The API decides what's done. */
const STEP_COPY: Record<KickoffStepKey, { title: string; lede: string; optional?: boolean }> = {
  prd: {
    title: 'The PRD',
    lede:
      'The Confluence page this feature is specified in. Everything after this is planned from what it ' +
      'says, and every quote in the analysis points back at a line of it.',
  },
  repos: {
    title: 'Where the code goes',
    lede:
      "The GitHub repos you'll build this feature in. Each is read at a pinned commit: its file tree, " +
      'languages, README and any API specs.',
  },
  dependencies: {
    title: 'What you rely on',
    lede:
      "Other teams' repos this feature calls or builds on. The analysis checks whether their APIs already " +
      'offer what the PRD needs, and flags what you must ask them for.',
    optional: true,
  },
  compliance: {
    title: 'Compliance',
    lede:
      'Which regulations and standards this feature must meet. Proposed from the PRD, each with the lines ' +
      'that triggered it. You approve the list, pick by hand, or approve that none apply.',
  },
  api_docs: {
    title: 'Our API docs',
    lede:
      'Links to the API docs this feature changes or extends. OpenAPI files are read as operations; any ' +
      'other page as text.',
    optional: true,
  },
  third_parties: {
    title: 'Third-party APIs',
    lede:
      'Providers the feature depends on, such as Salt Edge or Ninth Wave. Add each with its docs so the ' +
      'plan covers access, authentication and failure modes.',
    optional: true,
  },
  plan: {
    title: 'The analysis',
    lede:
      'The AI reads everything above and says what work is pending in which repo, what you need from ' +
      'others, and the Jira tasks in the order to do them. Edit them, then create them in your backlog.',
  },
};

/**
 * Feature Kickoff: a PRD taken, in seven steps, to an ordered backlog.
 *
 * Each step saves as it goes, so an analysis can be left and reopened, changed and run again.
 * Nothing here decides anything: what's done, what blocks a run, what the analysis found and what
 * was created all come from the API with their reasons.
 */
@Component({
  selector: 'sl-kickoff',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, DecimalPipe, FormsModule, GuideModal, KickoffAnalysisStep, NgTemplateOutlet],
  templateUrl: './kickoff.html',
  styleUrls: ['./kickoff-shared.css', './kickoff.css', './kickoff-steps.css'],
})
export class KickoffPage {
  private readonly api = inject(Api);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly projectId = input.required<string>();
  /** Connections are set up in Settings; the page links there rather than hiding the gap. */
  readonly openSettings = output<void>();

  readonly copy = STEP_COPY;
  readonly journey: { key: KickoffStepKey; label: string }[] = [
    { key: 'prd', label: 'PRD' },
    { key: 'repos', label: 'Repos' },
    { key: 'dependencies', label: 'Dependencies' },
    { key: 'compliance', label: 'Compliance' },
    { key: 'api_docs', label: 'API docs' },
    { key: 'third_parties', label: 'Third parties' },
    { key: 'plan', label: 'Analysis' },
  ];

  readonly status = signal<KickoffStatus | null>(null);
  readonly catalog = signal<KickoffCatalog | null>(null);
  readonly analyses = signal<KickoffAnalysisSummary[] | null>(null);
  readonly analysis = signal<KickoffAnalysis | null>(null);
  readonly step = signal<KickoffStepKey>('prd');
  /** Which action is in flight, so only its button says so. */
  readonly busy = signal<string | null>(null);
  readonly refusal = signal<Refusal | null>(null);
  /** Announced politely, so every result is heard, not only seen. */
  readonly announcement = signal('');

  readonly newPrdUrl = signal('');
  readonly confirmDelete = signal<number | null>(null);
  readonly editingTitle = signal(false);
  readonly titleDraft = signal('');
  readonly prdUrl = signal('');
  readonly showLines = signal(false);
  readonly drafts = signal<Record<string, string>>({});

  // Compliance: the person's working selection, saved when they approve it.
  readonly selected = signal<string[]>([]);
  readonly custom = signal<CustomCompliance[]>([]);
  readonly customName = signal('');
  readonly customNote = signal('');
  readonly showAllFrameworks = signal(false);

  readonly providerName = signal('');
  readonly providerDocs = signal('');

  readonly openGuide = signal(false);
  readonly guide = signal<PerspectiveGuide | null>(null);

  readonly stepIndex = computed(() => this.journey.findIndex((s) => s.key === this.step()));
  readonly steps = computed(() => this.analysis()?.steps ?? []);
  readonly doneCount = computed(() => this.steps().filter((s) => s.done).length);
  readonly frameworks = computed(() => this.catalog()?.frameworks ?? []);
  readonly suggestedKeys = computed(
    () => new Set(this.analysis()?.compliance.suggestions.map((s) => s.key).filter(Boolean) ?? []),
  );
  readonly otherFrameworks = computed(() =>
    this.frameworks().filter((f) => !this.suggestedKeys().has(f.key)),
  );
  /** The working selection differs from what was approved: it needs approving again. */
  readonly complianceChanged = computed(() => {
    const c = this.analysis()?.compliance;
    if (!c?.approved_by) return true;
    const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
    return (
      !same(this.selected(), c.selected) ||
      !same(
        this.custom().map((x) => x.name),
        c.custom.map((x) => x.name),
      )
    );
  });
  readonly approvedCount = computed(() => this.selected().length + this.custom().length);
  readonly providerKeys = computed(
    () => new Set(this.analysis()?.third_parties.providers.map((p) => p.key).filter(Boolean) ?? []),
  );
  readonly mentionedProviders = computed(() => {
    const a = this.analysis();
    if (!a) return [];
    return (this.catalog()?.providers ?? []).filter(
      (p) => a.third_parties.mentioned[p.key] && !this.providerKeys().has(p.key),
    );
  });
  readonly needsSetup = computed(
    () => this.status()?.connections.filter((c) => c.state === 'not_configured') ?? [],
  );

  constructor() {
    effect(() => {
      const id = this.projectId();
      // A project switch closes whatever belonged to the project you just left.
      untracked(() => this.reset(id));
    });
  }

  private reset(projectId: string): void {
    this.analysis.set(null);
    this.analyses.set(null);
    this.refusal.set(null);
    this.newPrdUrl.set('');
    if (!projectId) return;
    this.api.kickoffStatus(projectId).subscribe({
      next: (s) => this.status.set(s),
      error: () => this.status.set(null),
    });
    this.api.kickoffCatalog(projectId).subscribe({
      next: (c) => this.catalog.set(c),
      error: () => this.catalog.set(null),
    });
    this.loadAnalyses();
  }

  loadAnalyses(): void {
    this.api.kickoffAnalyses(this.projectId()).subscribe({
      next: (rows) => this.analyses.set(rows),
      error: (err) => {
        this.analyses.set([]);
        this.refusal.set(refusal(err, 'Saved analyses could not be loaded.'));
      },
    });
  }

  // --- Home ----------------------------------------------------------------------------------------

  start(): void {
    const url = this.newPrdUrl().trim();
    if (!url) return;
    this.run('start', this.api.createKickoffAnalysis(this.projectId(), url), (a) => {
      this.newPrdUrl.set('');
      this.show('prd');
      return `Read “${a.prd?.title}”, version ${a.prd?.version}. The analysis is saved.`;
    });
  }

  open(id: number): void {
    this.refusal.set(null);
    this.api.kickoffAnalysis(this.projectId(), id).subscribe({
      next: (a) => {
        this.adopt(a);
        const next = a.plan ? 'plan' : (a.steps.find((s) => !s.done)?.key ?? 'plan');
        this.show(next);
      },
      error: (err) => this.refusal.set(refusal(err, 'That analysis could not be opened.')),
    });
  }

  close(): void {
    this.analysis.set(null);
    this.refusal.set(null);
    this.editingTitle.set(false);
    this.loadAnalyses();
    afterNextRender(() => this.host.nativeElement.scrollIntoView({ block: 'start' }), {
      injector: this.injector,
    });
  }

  remove(id: number): void {
    this.busy.set(`delete-${id}`);
    this.api.deleteKickoffAnalysis(this.projectId(), id).subscribe({
      next: () => {
        this.busy.set(null);
        this.confirmDelete.set(null);
        this.announcement.set('Analysis deleted. Anything it created in Jira is still in Jira.');
        this.loadAnalyses();
      },
      error: (err) => {
        this.busy.set(null);
        this.refusal.set(writeRefusal(err, 'The analysis could not be deleted.'));
      },
    });
  }

  // --- Navigation -----------------------------------------------------------------------------------

  go(step: KickoffStepKey): void {
    this.refusal.set(null);
    this.show(step);
  }

  next(): void {
    const i = this.stepIndex();
    if (i < this.journey.length - 1) this.go(this.journey[i + 1].key);
  }

  prev(): void {
    const i = this.stepIndex();
    if (i > 0) this.go(this.journey[i - 1].key);
  }

  /** A new step starts at its top, with focus on its heading, so nobody lands mid-page. */
  private show(step: KickoffStepKey): void {
    this.step.set(step);
    this.showLines.set(false);
    afterNextRender(
      () => {
        const host = this.host.nativeElement;
        host.scrollIntoView({ block: 'start' });
        host.querySelector<HTMLElement>('.step-title')?.focus({ preventScroll: true });
      },
      { injector: this.injector },
    );
  }

  stepState(key: KickoffStepKey): 'done' | 'current' | 'todo' {
    if (this.step() === key) return 'current';
    return this.steps().find((s) => s.key === key)?.done ? 'done' : 'todo';
  }

  stepSummary(key: KickoffStepKey): string {
    return this.steps().find((s) => s.key === key)?.summary ?? '';
  }

  // --- Title ------------------------------------------------------------------------------------------

  editTitle(): void {
    this.titleDraft.set(this.analysis()?.title ?? '');
    this.editingTitle.set(true);
  }

  saveTitle(): void {
    const a = this.analysis();
    const title = this.titleDraft().trim();
    if (!a || !title || title === a.title) {
      this.editingTitle.set(false);
      return;
    }
    this.run('rename', this.api.renameKickoffAnalysis(this.projectId(), a.id, title), () => {
      this.editingTitle.set(false);
      return `Renamed to “${title}”.`;
    });
  }

  // --- Step 1: the PRD ---------------------------------------------------------------------------------

  rereadPrd(): void {
    const a = this.analysis();
    const url = (this.prdUrl() || a?.prd?.url || '').trim();
    if (!a || !url) return;
    this.run('prd', this.api.readKickoffPrd(this.projectId(), a.id, url), (next) => {
      return `Read “${next.prd?.title}”, version ${next.prd?.version}.`;
    });
  }

  // --- Steps 2, 3 and 5: lists of links ---------------------------------------------------------------

  draft(key: string): string {
    return this.drafts()[key] ?? '';
  }

  setDraft(key: string, value: string): void {
    this.drafts.update((d) => ({ ...d, [key]: value }));
  }

  repos(role: RepoRole): KickoffRepo[] {
    return this.analysis()?.[role].repos ?? [];
  }

  addRepo(role: RepoRole): void {
    const url = this.draft(role).trim();
    if (!url) return;
    const urls = [...this.repos(role).map((r) => r.url), ...url.split(/[\s,]+/).filter(Boolean)];
    this.saveRepos(role, urls, false, () => {
      this.setDraft(role, '');
      const added = this.repos(role).at(-1);
      return added?.ok ? `Read ${added.full_name} at ${added.commit}.` : `Couldn't read it: ${added?.error}`;
    });
  }

  removeRepo(role: RepoRole, url: string): void {
    this.saveRepos(
      role,
      this.repos(role)
        .map((r) => r.url)
        .filter((u) => u !== url),
      false,
      () => 'Removed.',
    );
  }

  refreshRepos(role: RepoRole): void {
    this.saveRepos(role, this.repos(role).map((r) => r.url), true, () => 'Read every repo again at its latest commit.');
  }

  skipDependencies(): void {
    this.saveRepos('dependencies', [], false, () => {
      this.next();
      return 'No dependencies: saved.';
    });
  }

  private saveRepos(role: RepoRole, urls: string[], refresh: boolean, done: () => string): void {
    const a = this.analysis();
    if (!a) return;
    this.run(role, this.api.setKickoffRepos(this.projectId(), a.id, role, urls, refresh), done);
  }

  docs(): KickoffDoc[] {
    return this.analysis()?.api_docs.docs ?? [];
  }

  addDoc(): void {
    const url = this.draft('api_docs').trim();
    if (!url) return;
    this.saveDocs([...this.docs().map((d) => d.url), ...url.split(/[\s,]+/).filter(Boolean)], false, () => {
      this.setDraft('api_docs', '');
      const added = this.docs().at(-1);
      return added?.ok ? `Read ${added.title}.` : `Couldn't read it: ${added?.error}`;
    });
  }

  removeDoc(url: string): void {
    this.saveDocs(
      this.docs()
        .map((d) => d.url)
        .filter((u) => u !== url),
      false,
      () => 'Removed.',
    );
  }

  refreshDocs(): void {
    this.saveDocs(this.docs().map((d) => d.url), true, () => 'Read every doc again.');
  }

  private saveDocs(urls: string[], refresh: boolean, done: () => string): void {
    const a = this.analysis();
    if (!a) return;
    this.run('api_docs', this.api.setKickoffDocs(this.projectId(), a.id, urls, refresh), done);
  }

  skipDocs(): void {
    this.saveDocs([], false, () => {
      this.next();
      return 'No API docs: saved.';
    });
  }

  // --- Step 4: compliance ---------------------------------------------------------------------------

  suggest(): void {
    const a = this.analysis();
    if (!a) return;
    this.run('suggest', this.api.suggestKickoffCompliance(this.projectId(), a.id), (next) => {
      const strong = next.compliance.suggestions.filter((s) => s.confidence === 'strong');
      if (!next.compliance.approved_by) {
        this.selected.set(strong.map((s) => s.key).filter(Boolean));
      }
      return `${next.compliance.suggestions.length} proposed, ${strong.length} strongly. Review and approve.`;
    });
  }

  isSelected(key: string): boolean {
    return this.selected().includes(key);
  }

  toggle(key: string): void {
    this.selected.update((all) => (all.includes(key) ? all.filter((k) => k !== key) : [...all, key]));
  }

  /** A proposal outside the catalog is taken as a custom item, with the model's reason as its note. */
  toggleOther(s: KickoffComplianceSuggestion): void {
    const have = this.custom().some((c) => c.name === s.name);
    this.custom.update((all) =>
      have ? all.filter((c) => c.name !== s.name) : [...all, { name: s.name, note: s.why.slice(0, 500) }],
    );
  }

  hasCustom(name: string): boolean {
    return this.custom().some((c) => c.name === name);
  }

  addCustom(): void {
    const name = this.customName().trim();
    if (!name || this.hasCustom(name)) return;
    this.custom.update((all) => [...all, { name, note: this.customNote().trim() }]);
    this.customName.set('');
    this.customNote.set('');
  }

  removeCustom(name: string): void {
    this.custom.update((all) => all.filter((c) => c.name !== name));
  }

  approve(): void {
    const a = this.analysis();
    if (!a) return;
    this.run(
      'approve',
      this.api.approveKickoffCompliance(this.projectId(), a.id, this.selected(), this.custom()),
      (next) => {
        const n = next.compliance.selected.length + next.compliance.custom.length;
        return n ? `${n} approved by ${next.compliance.approved_by}.` : `Approved: none apply.`;
      },
    );
  }

  framework(key: string): ComplianceFramework | undefined {
    return this.frameworks().find((f) => f.key === key);
  }

  // --- Step 6: third parties ----------------------------------------------------------------------------

  private providerList(): { key: string; name: string; docs_url: string }[] {
    return (this.analysis()?.third_parties.providers ?? []).map((p) => ({
      key: p.key,
      name: p.name,
      docs_url: p.docs_url,
    }));
  }

  addCatalogProvider(p: ProviderCatalogEntry): void {
    if (this.providerKeys().has(p.key)) return;
    this.saveProviders([...this.providerList(), { key: p.key, name: p.name, docs_url: p.docs_url }], () =>
      p.docs_url ? `Added ${p.name} and read its docs.` : `Added ${p.name}. Paste its docs link to read them.`,
    );
  }

  addCustomProvider(): void {
    const name = this.providerName().trim();
    if (!name) return;
    this.saveProviders(
      [...this.providerList(), { key: '', name, docs_url: this.providerDocs().trim() }],
      () => {
        this.providerName.set('');
        this.providerDocs.set('');
        return `Added ${name}.`;
      },
    );
  }

  removeProvider(name: string): void {
    this.saveProviders(
      this.providerList().filter((p) => p.name !== name),
      () => `Removed ${name}.`,
    );
  }

  setProviderDocs(name: string, url: string): void {
    const list = this.providerList();
    const current = list.find((p) => p.name === name);
    if (!current || current.docs_url === url.trim()) return;
    this.saveProviders(
      list.map((p) => (p.name === name ? { ...p, docs_url: url.trim() } : p)),
      () => `Read ${name}'s docs.`,
    );
  }

  skipProviders(): void {
    this.saveProviders([], () => {
      this.next();
      return 'No third-party APIs: saved.';
    });
  }

  private saveProviders(providers: { key: string; name: string; docs_url: string }[], done: () => string): void {
    const a = this.analysis();
    if (!a) return;
    this.run('third_parties', this.api.setKickoffProviders(this.projectId(), a.id, providers), done);
  }

  // --- Guide ------------------------------------------------------------------------------------------

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

  // --- Presentation (tone is always colour plus glyph) ---------------------------------------------------

  connectionTone(c: KickoffConnection): Tone {
    if (c.state === 'ready') return { glyph: '✓', label: c.via ? `Connected · ${c.via}` : 'Connected', tone: 'good' };
    if (c.state === 'fallback') return { glyph: '!', label: 'Limited', tone: 'watch' };
    return { glyph: '?', label: 'Not connected', tone: 'missing' };
  }

  statusTone(status: string, stale = false): Tone {
    if (stale) return { glyph: '!', label: 'Inputs changed', tone: 'watch' };
    switch (status) {
      case 'created':
        return { glyph: '✓', label: 'In Jira', tone: 'good' };
      case 'partial':
        return { glyph: '✕', label: 'Partly created', tone: 'poor' };
      case 'analysed':
        return { glyph: '◆', label: 'Analysed', tone: 'accent' };
      default:
        return { glyph: '○', label: 'Draft', tone: 'neutral' };
    }
  }

  confidenceTone(s: KickoffComplianceSuggestion): Tone {
    return s.confidence === 'strong'
      ? { glyph: '✓', label: 'Strong', tone: 'good' }
      : { glyph: '?', label: 'Possible', tone: 'watch' };
  }

  languages(repo: KickoffRepo): string {
    return repo.languages.map((l) => `${l.name} ${Math.round(l.share * 100)}%`).join(' · ');
  }

  specOperations(repo: KickoffRepo): number {
    return repo.specs.reduce((n, s) => n + s.operation_count, 0);
  }

  // --- Writes ------------------------------------------------------------------------------------------

  adopt(a: KickoffAnalysis): void {
    const before = this.analysis();
    this.analysis.set(a);
    this.prdUrl.set(a.prd?.url ?? '');
    const c = a.compliance;
    // A different analysis, or a new approval: the working selection starts from the record.
    if (!before || before.id !== a.id || before.compliance.approved_at !== c.approved_at) {
      this.selected.set(
        c.approved_by
          ? [...c.selected]
          : c.suggestions.filter((s) => s.confidence === 'strong' && s.key).map((s) => s.key),
      );
      this.custom.set(c.custom.map((x) => ({ ...x })));
    }
  }

  onAnalysisChange(a: KickoffAnalysis): void {
    this.adopt(a);
  }

  private run(label: string, call: Observable<KickoffAnalysis>, done: (a: KickoffAnalysis) => string): void {
    this.busy.set(label);
    this.refusal.set(null);
    call.subscribe({
      next: (a) => {
        this.adopt(a);
        this.busy.set(null);
        this.announcement.set(done(a));
      },
      error: (err) => {
        this.busy.set(null);
        // The API's refusal in the API's words, with its reasons as a list.
        const refused = writeRefusal(err, errorMessage(err, 'That step was refused.'));
        this.refusal.set(refused);
        this.announcement.set(refused.message);
      },
    });
  }
}
