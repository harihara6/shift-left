import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, of, switchMap } from 'rxjs';

import { Api } from '../../core/api';
import { errorMessage } from '../../core/errors';
import { Comparison, PerspectiveGuide, TeamInsights as TeamInsightsPayload } from '../../core/models';
import { PeriodStore } from '../../core/period-store';
import { FlowBanner, FreshnessStrip } from '../../ui/banners';
import { Chart } from '../../ui/chart';
import { GuideModal } from '../../ui/guide-modal';
import { MetricTile } from '../../ui/metric-tile';
import { RagBadge } from '../../ui/rag-badge';

/**
 * Team Insights - the Delivery Control perspective.
 *
 * Everything here is pace, size and defect pressure. None of it is evidence, which is why the
 * flow banner and its cross-link are not optional decoration.
 *
 * No period is named in this component either: it renders whatever window the filter resolved,
 * and takes its column headings from the response.
 */
@Component({
  selector: 'sl-team-insights',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MetricTile, Chart, RagBadge, FlowBanner, FreshnessStrip, GuideModal],
  templateUrl: './team-insights.html',
  styleUrl: './team-insights.css',
})
export class TeamInsights {
  private readonly api = inject(Api);
  private readonly periods = inject(PeriodStore);

  readonly projectId = input.required<string>();
  /** The window the API actually resolved, so the header's filter can show what is on screen. */
  readonly comparisonChange = output<Comparison | null>();
  /** Structural, not decorative: a flow view always offers the way back to the record. */
  readonly openEvidence = output<void>();
  readonly openGuide = signal(false);
  readonly guide = signal<PerspectiveGuide | null>(null);
  readonly error = signal<string | null>(null);

  /** Any change to the project or the reporting window refetches the whole page. */
  private readonly request = computed(() => ({
    projectId: this.projectId(),
    selection: this.periods.selection(),
  }));

  readonly data = toSignal(
    toObservable(this.request).pipe(
      switchMap(({ projectId, selection }) =>
        this.api.teamInsights(projectId, selection).pipe(
          catchError((err) => {
            this.error.set(
              errorMessage(err, 'This project has no delivery snapshot for that window. An absent snapshot is a gap, not an empty dashboard.'),
            );
            return of(null as TeamInsightsPayload | null);
          }),
        ),
      ),
    ),
    { initialValue: null },
  );

  constructor() {
    effect(() => {
      const payload = this.data();
      if (payload) this.error.set(null);
      this.comparisonChange.emit(payload?.comparison ?? null);
    });
  }

  showGuide(): void {
    if (this.guide()) {
      this.openGuide.set(true);
      return;
    }
    this.api.guide('delivery').subscribe({
      next: (guide) => {
        this.guide.set(guide);
        this.openGuide.set(true);
      },
      // Leave the page as it is; the guide button stays available to retry.
      error: () => this.openGuide.set(false),
    });
  }
}
