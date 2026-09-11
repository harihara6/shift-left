import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, of, switchMap } from 'rxjs';

import { Api } from '../../core/api';
import { errorMessage, writeRefusal } from '../../core/errors';
import { FeatureReadiness as Payload, FeatureRow, PerspectiveGuide } from '../../core/models';
import { FreshnessStrip } from '../../ui/banners';
import { GuideModal } from '../../ui/guide-modal';
import { MetricTile } from '../../ui/metric-tile';
import { RagBadge } from '../../ui/rag-badge';
import { EvidencePanel } from './evidence-panel';

/**
 * Feature Readiness - the Engineering Discipline perspective, and the evidence of record.
 *
 * This is where a review opens and where every flow view links back to. Nothing on the page is
 * computed from a weighted score: each status arrives from the API carrying the list of
 * artifacts that produced it.
 */
@Component({
  selector: 'sl-feature-readiness',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MetricTile, RagBadge, FreshnessStrip, GuideModal, EvidencePanel],
  templateUrl: './feature-readiness.html',
  styleUrl: './feature-readiness.css',
})
export class FeatureReadinessPage {
  private readonly api = inject(Api);

  readonly projectId = input.required<string>();
  /** The evidence record is the destination of every cross-link; this one goes the other way. */
  readonly openFlow = output<void>();

  readonly openGuide = signal(false);
  readonly guide = signal<PerspectiveGuide | null>(null);
  readonly error = signal<string | null>(null);
  readonly selectedKey = signal<string | null>(null);
  /** Announced politely, so an acknowledgement is not a silent visual change. */
  readonly announcement = signal('');
  /** A refused write, shown on the page as well as announced. */
  readonly notice = signal<string | null>(null);

  private readonly override = signal<Payload | null>(null);

  private readonly fetched = toSignal(
    toObservable(computed(() => this.projectId())).pipe(
      switchMap((id) =>
        this.api.featureReadiness(id).pipe(
          catchError((err) => {
            this.error.set(
              errorMessage(err, 'No feature is tracked for this project yet. That is a gap in tagging, not an empty gate.'),
            );
            return of(null as Payload | null);
          }),
        ),
      ),
    ),
    { initialValue: null },
  );

  /** A write returns the recomputed page; until then the fetched payload stands. */
  readonly data = computed(() => this.override() ?? this.fetched());

  readonly selected = computed<FeatureRow | null>(
    () => this.data()?.features.find((f) => f.key === this.selectedKey()) ?? null,
  );

  readonly tierClass = (tier: string) =>
    'tier-' + tier.toLowerCase().replace(/[^a-z]+/g, '-').replace(/(^-|-$)/g, '');

  constructor() {
    effect(() => {
      if (this.fetched()) this.error.set(null);
      // A project switch closes a panel that belongs to the project you just left.
      this.projectId();
      this.selectedKey.set(null);
      this.override.set(null);
      this.notice.set(null);
    });
  }

  showGuide(): void {
    if (this.guide()) {
      this.openGuide.set(true);
      return;
    }
    this.api.guide('discipline').subscribe({
      next: (guide) => {
        this.guide.set(guide);
        this.openGuide.set(true);
      },
      error: (err) => this.refuse(errorMessage(err, 'The guide for this page could not be loaded.')),
    });
  }

  acknowledge(actionId: number, signalName: string): void {
    this.notice.set(null);
    this.api.acknowledgeAction(this.projectId(), actionId).subscribe({
      next: (action) => {
        const current = this.data();
        if (current) {
          this.override.set({
            ...current,
            actions: current.actions.map((a) => (a.id === action.id ? action : a)),
          });
        }
        this.announcement.set(
          `${signalName} acknowledged by ${action.acknowledged_by}. The evidence gap is unchanged.`,
        );
      },
      error: (err) => this.refuse(writeRefusal(err, 'The acknowledgement was not recorded.').message),
    });
  }

  acceptDraft(featureKey: string): void {
    this.notice.set(null);
    this.api.acceptAiDraft(this.projectId(), featureKey).subscribe({
      next: (payload) => {
        this.override.set(payload);
        this.announcement.set(`AI draft for ${featureKey} accepted and recorded.`);
      },
      error: (err) => this.refuse(writeRefusal(err, 'The acceptance was not recorded.').message),
    });
  }

  /** A refusal is shown and announced - a write that silently did nothing reads as success. */
  private refuse(message: string): void {
    this.notice.set(message);
    this.announcement.set(message);
  }
}
