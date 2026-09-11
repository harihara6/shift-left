import { ChangeDetectionStrategy, Component, computed, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../../core/api';
import { errorMessage } from '../../core/errors';
import { OnboardingBinding, OnboardingDraft, OnboardingResult, OnboardingSlot } from '../../core/models';

type Step = 'name' | 'evidence' | 'bindings' | 'create';

/**
 * Guided project setup: type the name the team already uses, confirm what the sources say it
 * is, then create the project from it.
 *
 * The wizard is an alternate path to the manual form, never a replacement. If nothing can be
 * searched — Rovo MCP not enabled, connectors not configured, a name nothing matches — it says
 * so and hands the work back to the manual form rather than proposing something empty.
 *
 * Nothing here is applied as it is drafted. The whole screen is a proposal until Create, which
 * is the call that records a named person accepting it.
 */
@Component({
  selector: 'sl-onboarding-wizard',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  host: { '(document:keydown.escape)': 'closed.emit()' },
  templateUrl: './onboarding-wizard.html',
  styleUrl: './onboarding-wizard.css',
})
export class OnboardingWizard {
  private readonly api = inject(Api);

  readonly closed = output<void>();
  readonly created = output<OnboardingResult>();

  readonly step = signal<Step>('name');
  readonly hint = signal('');
  readonly busy = signal(false);
  readonly error = signal('');
  readonly draft = signal<OnboardingDraft | null>(null);

  /** Slots the person confirmed. A proposal is not a decision until it is ticked. */
  readonly acceptedSlots = signal<Set<string>>(new Set());
  readonly enabledTemplates = signal<Set<string>>(new Set());
  /** Per-widget query edits, keyed template/widget. Absent means "as proposed". */
  readonly edits = signal<Record<string, string>>({});

  readonly identity = signal({ key: '', name: '', owner: '' });

  readonly steps: { id: Step; label: string }[] = [
    { id: 'name', label: 'Name' },
    { id: 'evidence', label: 'Evidence' },
    { id: 'bindings', label: 'Bindings' },
    { id: 'create', label: 'Create' },
  ];

  readonly searchableSources = computed(
    () => this.draft()?.sources.filter((s) => s.available) ?? [],
  );
  readonly blockedSources = computed(() => this.draft()?.sources.filter((s) => !s.available) ?? []);

  /** Templates worth showing: the ones discovery could bind at least one widget on. */
  readonly proposedTemplates = computed(
    () => this.draft()?.templates.filter((t) => t.propose_enabled) ?? [],
  );
  readonly unproposedTemplates = computed(
    () => this.draft()?.templates.filter((t) => !t.propose_enabled) ?? [],
  );

  readonly boundCount = computed(
    () =>
      this.proposedTemplates()
        .filter((t) => this.enabledTemplates().has(t.template_key))
        .flatMap((t) => t.bindings)
        .filter((b) => this.queryFor(b).trim()).length,
  );
  readonly emptyCount = computed(
    () =>
      this.proposedTemplates()
        .filter((t) => this.enabledTemplates().has(t.template_key))
        .flatMap((t) => t.bindings)
        .filter((b) => !this.queryFor(b).trim()).length,
  );

  search(): void {
    const hint = this.hint().trim();
    if (hint.length < 2) return;
    this.busy.set(true);
    this.error.set('');
    this.api.discoverProject(hint).subscribe({
      next: (draft) => {
        this.busy.set(false);
        this.draft.set(draft);
        // Everything starts unconfirmed on purpose — a proposal is read, then ticked.
        this.acceptedSlots.set(new Set(draft.slots.map((s) => s.slot)));
        this.enabledTemplates.set(
          new Set(draft.templates.filter((t) => t.propose_enabled).map((t) => t.template_key)),
        );
        this.edits.set({});
        this.identity.set({
          key: draft.project_key,
          name: draft.project_name,
          owner: draft.owner,
        });
        this.step.set('evidence');
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(errorMessage(err, 'Discovery could not run. Set the project up by hand.'));
      },
    });
  }

  go(step: Step): void {
    if (step !== 'name' && !this.draft()) return;
    this.step.set(step);
  }

  toggleSlot(slot: string): void {
    this.acceptedSlots.update((current) => {
      const next = new Set(current);
      if (next.has(slot)) next.delete(slot);
      else next.add(slot);
      return next;
    });
  }

  toggleTemplate(key: string): void {
    this.enabledTemplates.update((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  /**
   * The query as it currently stands: edited, or proposed — and empty whenever a slot it was
   * built from has been un-ticked. Rejecting the evidence has to reject what was built on it,
   * or the person has rejected a source and kept the query that used it.
   */
  queryFor(binding: OnboardingBinding): string {
    const key = this.keyOf(binding);
    const edited = this.edits()[key];
    if (edited !== undefined) return edited;
    const rejected = binding.filled_slots.some((slot) => !this.acceptedSlots().has(slot));
    return rejected ? '' : binding.query;
  }

  editQuery(binding: OnboardingBinding, query: string): void {
    this.edits.update((all) => ({ ...all, [this.keyOf(binding)]: query }));
  }

  keyOf(binding: OnboardingBinding): string {
    return `${binding.template_key}/${binding.widget_name}`;
  }

  /** Colour is never the only carrier — every state has a glyph as well (WCAG 2.2 AA). */
  stateOf(binding: OnboardingBinding): { glyph: string; label: string; tone: string } {
    if (!this.queryFor(binding).trim()) {
      return { glyph: '—', label: 'Missing — bind it by hand', tone: 'missing' };
    }
    if (binding.generic) {
      return { glyph: '!', label: 'Carried from the template — check it', tone: 'watch' };
    }
    if (binding.validated) {
      return { glyph: '✓', label: `Previewed ${binding.row_count} row(s)`, tone: 'good' };
    }
    return { glyph: '!', label: 'Bound, but returned nothing on preview', tone: 'watch' };
  }

  confidenceLabel(slot: OnboardingSlot): string {
    const pct = Math.round(slot.confidence * 100);
    if (!pct) return 'unscored';
    return `${pct}% confident`;
  }

  slotLabel(slot: string): string {
    return slot.replace(/_/g, ' ');
  }

  create(): void {
    const draft = this.draft();
    const identity = this.identity();
    if (!draft || !identity.key || !identity.name || !identity.owner) return;
    this.busy.set(true);
    this.error.set('');

    const templates = [...this.enabledTemplates()];
    const bindings = draft.templates
      .filter((t) => this.enabledTemplates().has(t.template_key))
      .flatMap((t) => t.bindings)
      .map((b) => ({
        template_key: b.template_key,
        widget_name: b.widget_name,
        query: this.queryFor(b),
      }));

    this.api
      .acceptOnboarding(draft.id, { ...identity, templates, bindings })
      .subscribe({
        next: (result) => {
          this.busy.set(false);
          this.created.emit(result);
        },
        error: (err) => {
          this.busy.set(false);
          this.error.set(errorMessage(err, 'The project could not be created.'));
        },
      });
  }
}
