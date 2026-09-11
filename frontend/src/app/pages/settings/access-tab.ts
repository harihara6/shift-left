import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { Api } from '../../core/api';
import { errorMessage } from '../../core/errors';
import { AccessModelEntry } from '../../core/models';

/** The written positioning of the authorization model, served by the API rather than restated here. */
@Component({
  selector: 'sl-access-tab',
  changeDetection: ChangeDetectionStrategy.OnPush,
  styleUrl: './settings.css',
  template: `
    <div class="access-page">
      <section class="model-lead">
        <div class="label-caps" style="color: #6e717a">The model in one line</div>
        <h3>
          SSO says who you are, the project says what you may see, and the service account decides
          what could ever be ingested in the first place.
        </h3>
        <p>
          Access is not configurable per widget by design — a widget is only ever as visible as the
          project it lives in. That keeps the rule small enough to reason about during an incident.
        </p>
      </section>
      @if (error(); as message) { <p class="notice" role="alert">{{ message }}</p> }
      @for (entry of entries(); track entry.title) {
        <section class="card model-entry">
          <h4>{{ entry.title }}</h4>
          <p>{{ entry.detail }}</p>
        </section>
      }
    </div>
  `,
  styles: [`.access-page { display: flex; flex-direction: column; gap: 14px; max-width: 920px; }`],
})
export class AccessTab {
  private readonly api = inject(Api);
  readonly entries = signal<AccessModelEntry[]>([]);
  readonly error = signal<string | null>(null);

  constructor() {
    this.api.accessModel().subscribe({
      next: (entries) => this.entries.set(entries),
      error: (err) => this.error.set(errorMessage(err, 'The access model could not be loaded.')),
    });
  }
}
