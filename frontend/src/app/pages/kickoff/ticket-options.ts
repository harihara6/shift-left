import {
  ChangeDetectionStrategy,
  Component,
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
import { errorMessage } from '../../core/errors';
import { BacklogFields, JiraTicketDefaults, KickoffAnalysis } from '../../core/models';
import { Modal } from '../../ui/modal';

/**
 * What every ticket this analysis creates should carry, on top of the two labels that let
 * ShiftLeft find its own tickets again.
 *
 * Every choice is offered by the project itself rather than typed: a component that doesn't exist
 * would otherwise fail every single create. The server checks them against Jira again before it
 * writes, because this panel can be minutes old by the time the button is pressed.
 */
@Component({
  selector: 'sl-ticket-options',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, Modal],
  templateUrl: './ticket-options.html',
  styleUrls: ['./kickoff-shared.css', './ticket-options.css'],
})
export class TicketOptions {
  private readonly api = inject(Api);

  readonly projectId = input.required<string>();
  readonly analysisId = input.required<number>();
  readonly backlogUrl = input.required<string>();
  readonly options = input.required<JiraTicketDefaults>();
  readonly saved = output<KickoffAnalysis>();
  readonly closed = output<void>();

  readonly draft = signal<JiraTicketDefaults | null>(null);
  readonly fields = signal<BacklogFields | null>(null);
  readonly problem = signal('');
  readonly loading = signal(true);
  readonly saving = signal(false);

  readonly labelText = computed(() => (this.draft()?.labels ?? []).join(', '));

  constructor() {
    // Inputs are only readable once bound, so the one-time load runs in an effect rather than here.
    effect(() => {
      const [projectId, analysisId, url, options] = [
        this.projectId(),
        this.analysisId(),
        this.backlogUrl().trim(),
        this.options(),
      ];
      untracked(() => {
        if (this.draft()) return;
        this.draft.set({ ...options, labels: [...options.labels], components: [...options.components] });
        if (!url) {
          this.loading.set(false);
          this.problem.set('Paste the backlog link first: the choices below come from that project.');
          return;
        }
        this.api.kickoffBacklogFields(projectId, analysisId, url).subscribe({
          next: (fields) => {
            this.fields.set(fields);
            this.loading.set(false);
          },
          error: (err) => {
            this.loading.set(false);
            this.problem.set(errorMessage(err, "That project's fields could not be read."));
          },
        });
      });
    });
  }

  patch<K extends keyof JiraTicketDefaults>(key: K, value: JiraTicketDefaults[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  setLabels(text: string): void {
    this.patch('labels', text.split(',').map((v) => v.trim()).filter(Boolean));
  }

  toggleComponent(name: string): void {
    const current = this.draft()?.components ?? [];
    this.patch('components', current.includes(name) ? current.filter((c) => c !== name) : [...current, name]);
  }

  save(): void {
    const body = this.draft();
    if (!body) return;
    this.saving.set(true);
    this.api.setKickoffBacklogOptions(this.projectId(), this.analysisId(), body).subscribe({
      next: (a) => {
        this.saving.set(false);
        this.saved.emit(a);
      },
      error: (err) => {
        this.saving.set(false);
        this.problem.set(errorMessage(err, 'Those options were not saved.'));
      },
    });
  }
}
