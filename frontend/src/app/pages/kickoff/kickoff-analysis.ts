import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../../core/api';
import { Refusal, errorMessage, writeRefusal } from '../../core/errors';
import {
  Estimate,
  KickoffAnalysis,
  KickoffCatalog,
  KickoffStatus,
  KickoffStepKey,
  KickoffTask,
  KickoffTaskInput,
  KickoffTicket,
  ModelProvider,
  TaskType,
} from '../../core/models';

interface Tone {
  glyph: string;
  label: string;
  tone: string;
}

/** A task as edited here, with what the API said about it when it was drafted. */
interface Row extends KickoffTaskInput {
  source: KickoffTask | null;
}

const TYPES: TaskType[] = ['Story', 'Task', 'Spike'];
const ESTIMATES: Estimate[] = ['XS', 'S', 'M', 'L', 'XL'];

/** The backend's slug for a custom compliance item (kickoff.py `_slug`). */
function slug(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40) || 'item'
  );
}

/**
 * Step 7: run the analysis, read it, edit the tasks, and create them in the backlog.
 *
 * The draft is labelled with who drafted it wherever it's shown, and counts toward nothing until
 * someone creates it in Jira (product rule 6). A plan older than its inputs says which ones
 * changed; the API refuses to create it until it's run again.
 */
@Component({
  selector: 'sl-kickoff-analysis',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule],
  templateUrl: './kickoff-analysis.html',
  styleUrls: ['./kickoff-shared.css', './kickoff-analysis.css', './kickoff-tasks.css'],
})
export class KickoffAnalysisStep {
  private readonly api = inject(Api);
  private readonly destroyRef = inject(DestroyRef);

  readonly projectId = input.required<string>();
  readonly analysis = input.required<KickoffAnalysis>();
  readonly status = input<KickoffStatus | null>(null);
  readonly catalog = input<KickoffCatalog | null>(null);
  readonly changed = output<KickoffAnalysis>();
  readonly goStep = output<KickoffStepKey>();
  readonly openSettings = output<void>();

  readonly types = TYPES;
  readonly estimates = ESTIMATES;

  readonly providerKey = signal('');
  readonly model = signal('');
  readonly running = signal(false);
  readonly elapsed = signal(0);
  readonly confirmRun = signal(false);
  readonly refusal = signal<Refusal | null>(null);
  readonly announcement = signal('');

  /** Unsaved task edits. Null means "as the API last returned them". */
  readonly draft = signal<Row[] | null>(null);
  readonly epicDraft = signal<string | null>(null);
  readonly editing = signal<number | null>(null);
  readonly form = signal<Row | null>(null);
  readonly acText = signal('');
  readonly expanded = signal<Set<string>>(new Set());
  readonly saving = signal(false);

  readonly backlogUrl = signal('');
  readonly confirmCreate = signal(false);
  readonly creating = signal(false);

  private timer: ReturnType<typeof setInterval> | null = null;
  private newCount = 0;

  readonly plan = computed(() => this.analysis().plan);
  readonly providers = computed<ModelProvider[]>(() => this.status()?.providers ?? []);
  readonly provider = computed(() => this.providers().find((p) => p.key === this.providerKey()) ?? null);
  readonly inputs = computed(() => this.analysis().steps.filter((s) => s.key !== 'plan'));
  readonly rows = computed<Row[]>(
    () =>
      this.draft() ??
      (this.plan()?.tasks ?? []).map((t) => ({
        ref: t.ref,
        title: t.title,
        type: t.type,
        repo: t.repo,
        description: t.description,
        acceptance_criteria: [...t.acceptance_criteria],
        depends_on: [...t.depends_on],
        estimate: t.estimate,
        compliance: [...t.compliance],
        source: t,
      })),
  );
  readonly epicTitle = computed(() => this.epicDraft() ?? this.plan()?.epic_title ?? '');
  readonly dirty = computed(() => this.draft() !== null || this.epicDraft() !== null);
  readonly codeRepos = computed(() => this.analysis().repos.repos.filter((r) => r.ok).map((r) => r.full_name));
  readonly complianceNames = computed(() => {
    const c = this.analysis().compliance;
    const names: Record<string, string> = {};
    for (const key of c.selected) {
      names[key] = this.catalog()?.frameworks.find((f) => f.key === key)?.name ?? key;
    }
    for (const x of c.custom) names[`custom-${slug(x.name)}`] = x.name;
    return names;
  });
  readonly complianceKeys = computed(() => Object.keys(this.complianceNames()));
  readonly stale = computed(() => this.plan()?.stale ?? []);
  readonly jira = computed(() => this.status()?.connections.find((c) => c.key === 'jira') ?? null);
  readonly tickets = computed(() => {
    const map = new Map<string, KickoffTicket>();
    for (const t of this.analysis().backlog?.tickets ?? []) map.set(t.ref, t);
    return map;
  });
  readonly failedTickets = computed(() => this.analysis().backlog?.failed ?? 0);
  readonly allTickets = computed(() => {
    const b = this.analysis().backlog;
    return b ? [b.epic, ...b.tickets] : [];
  });
  readonly canCreate = computed(
    () =>
      !!this.plan()?.tasks.length &&
      !this.stale().length &&
      !this.dirty() &&
      !!this.backlogUrl().trim() &&
      this.jira()?.state === 'ready',
  );

  constructor() {
    effect(() => {
      const st = this.status();
      untracked(() => {
        if (st && !this.providerKey()) this.pick(st.default_provider);
      });
    });
    effect(() => {
      const a = this.analysis();
      untracked(() => {
        if (!this.backlogUrl()) this.backlogUrl.set(a.backlog_target?.url ?? a.backlog?.url ?? '');
      });
    });
    this.destroyRef.onDestroy(() => this.stopTimer());
  }

  pick(key: string): void {
    this.providerKey.set(key);
    const p = this.providers().find((x) => x.key === key);
    this.model.set(p?.default_model || p?.models[0]?.id || '');
  }

  // --- Running ------------------------------------------------------------------------------------

  run(): void {
    if (this.plan() && !this.confirmRun()) {
      this.confirmRun.set(true);
      return;
    }
    const a = this.analysis();
    this.confirmRun.set(false);
    this.refusal.set(null);
    this.running.set(true);
    this.startTimer();
    this.announcement.set('Running the analysis. This can take a few minutes.');
    this.api.runKickoffAnalysis(this.projectId(), a.id, this.providerKey(), this.model()).subscribe({
      next: (next) => {
        this.stopTimer();
        this.running.set(false);
        this.discard();
        this.changed.emit(next);
        const plan = next.plan!;
        this.announcement.set(`Drafted by ${plan.drafted_by}: ${plan.tasks.length} tasks. Review them below.`);
      },
      error: (err) => {
        this.stopTimer();
        this.running.set(false);
        this.fail(err, 'The analysis could not run.');
      },
    });
  }

  private startTimer(): void {
    this.stopTimer();
    this.elapsed.set(0);
    const started = Date.now();
    this.timer = setInterval(() => this.elapsed.set(Math.round((Date.now() - started) / 1000)), 1000);
  }

  private stopTimer(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  elapsedLabel(): string {
    const s = this.elapsed();
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  // --- Editing tasks ------------------------------------------------------------------------------

  private working(): Row[] {
    return this.rows().map((r) => ({ ...r, depends_on: [...r.depends_on] }));
  }

  move(index: number, by: -1 | 1): void {
    const rows = this.working();
    const to = index + by;
    if (to < 0 || to >= rows.length) return;
    [rows[index], rows[to]] = [rows[to], rows[index]];
    this.draft.set(rows);
    this.announcement.set(`Moved “${rows[to].title}” to position ${to + 1}. Save to keep it.`);
  }

  removeTask(index: number): void {
    const rows = this.working();
    const [gone] = rows.splice(index, 1);
    for (const r of rows) r.depends_on = r.depends_on.filter((d) => d !== gone.ref);
    this.draft.set(rows);
    this.editing.set(null);
    this.announcement.set(`Removed “${gone.title}”. Save to keep it.`);
  }

  addTask(): void {
    const rows = this.working();
    this.newCount += 1;
    rows.push({
      ref: `new-${this.newCount}`,
      title: '',
      type: 'Task',
      repo: '',
      description: '',
      acceptance_criteria: [],
      depends_on: [],
      estimate: 'M',
      compliance: [],
      source: null,
    });
    this.draft.set(rows);
    this.edit(rows.length - 1);
  }

  edit(index: number): void {
    const row = this.rows()[index];
    this.form.set({ ...row, depends_on: [...row.depends_on], compliance: [...row.compliance] });
    this.acText.set(row.acceptance_criteria.join('\n'));
    this.editing.set(index);
  }

  patch(changes: Partial<Row>): void {
    this.form.update((f) => (f ? { ...f, ...changes } : f));
  }

  toggleIn(field: 'depends_on' | 'compliance', value: string): void {
    this.form.update((f) => {
      if (!f) return f;
      const list = f[field];
      return { ...f, [field]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] };
    });
  }

  applyEdit(): void {
    const index = this.editing();
    const f = this.form();
    if (index === null || !f || !f.title.trim()) return;
    const rows = this.working();
    rows[index] = {
      ...f,
      title: f.title.trim(),
      acceptance_criteria: this.acText()
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean),
    };
    this.draft.set(rows);
    this.editing.set(null);
    this.form.set(null);
  }

  cancelEdit(): void {
    const index = this.editing();
    // A brand-new task abandoned before it had a title isn't kept.
    if (index !== null && !this.rows()[index]?.title) {
      const rows = this.working();
      rows.splice(index, 1);
      this.draft.set(rows);
    }
    this.editing.set(null);
    this.form.set(null);
  }

  /** Tasks above `index` that already exist server-side: what a task may depend on. */
  earlier(index: number): Row[] {
    return this.rows()
      .slice(0, index)
      .filter((r) => !r.ref.startsWith('new-'));
  }

  saveTasks(): void {
    const a = this.analysis();
    this.saving.set(true);
    this.refusal.set(null);
    const tasks: KickoffTaskInput[] = this.rows().map(({ source: _source, ...t }) => ({
      ...t,
      ref: t.ref.startsWith('new-') ? '' : t.ref,
    }));
    this.api.editKickoffPlan(this.projectId(), a.id, this.epicTitle().trim(), tasks).subscribe({
      next: (next) => {
        this.saving.set(false);
        this.discard();
        this.changed.emit(next);
        this.announcement.set(`Saved ${next.plan?.tasks.length} tasks, recorded as edited by ${next.plan?.edited_by}.`);
      },
      error: (err) => {
        this.saving.set(false);
        this.fail(err, 'The tasks could not be saved.');
      },
    });
  }

  discard(): void {
    this.draft.set(null);
    this.epicDraft.set(null);
    this.editing.set(null);
    this.form.set(null);
  }

  toggleExpanded(ref: string): void {
    this.expanded.update((all) => {
      const next = new Set(all);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
  }

  // --- Creating the backlog --------------------------------------------------------------------------

  create(): void {
    if (!this.confirmCreate()) {
      this.confirmCreate.set(true);
      return;
    }
    const a = this.analysis();
    this.confirmCreate.set(false);
    this.creating.set(true);
    this.refusal.set(null);
    this.api.createKickoffBacklog(this.projectId(), a.id, this.backlogUrl().trim()).subscribe({
      next: (next) => {
        this.creating.set(false);
        this.changed.emit(next);
        const b = next.backlog!;
        const all = [b.epic, ...b.tickets];
        const made = all.filter((t) => t.status === 'created').length;
        const had = all.filter((t) => t.status === 'exists').length;
        this.announcement.set(
          `${made} created and ${had} already there in ${b.project_key}` +
            (b.failed ? `; ${b.failed} failed, each with its reason.` : '.'),
        );
      },
      error: (err) => {
        this.creating.set(false);
        this.fail(err, 'Nothing was created.');
      },
    });
  }

  // --- Presentation (tone is always colour plus glyph) ------------------------------------------------

  needTone(status: string): Tone {
    if (status === 'available') return { glyph: '✓', label: 'Available', tone: 'good' };
    if (status === 'missing') return { glyph: '✕', label: 'Missing', tone: 'poor' };
    return { glyph: '?', label: 'Unclear', tone: 'watch' };
  }

  ticketTone(status: string): Tone {
    if (status === 'created') return { glyph: '✓', label: 'Created', tone: 'good' };
    if (status === 'exists') return { glyph: '✓', label: 'Already there', tone: 'good' };
    return { glyph: '✕', label: 'Failed', tone: 'poor' };
  }

  originLabel(row: Row): string {
    const t = row.source;
    if (!t) return 'New · not saved';
    const by = t.origin === 'claude' ? 'Claude' : t.origin === 'rules' ? 'Rules' : 'Added by a person';
    return t.edited_by ? `${by} · edited by ${t.edited_by}` : by;
  }

  position(ref: string): number {
    return this.rows().findIndex((r) => r.ref === ref) + 1;
  }

  after(row: Row): string {
    return row.depends_on.map((ref) => this.position(ref)).join(', ');
  }

  private fail(err: unknown, fallback: string): void {
    const refused = writeRefusal(err, errorMessage(err, fallback));
    this.refusal.set(refused);
    this.announcement.set(refused.message);
  }
}
