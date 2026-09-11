import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Observable, catchError, of, switchMap } from 'rxjs';

import { Api } from '../../core/api';
import { Refusal, errorMessage, refusal, writeRefusal } from '../../core/errors';
import { PerspectiveGuide, RolloutBoard } from '../../core/models';
import { FreshnessStrip } from '../../ui/banners';
import { Chart } from '../../ui/chart';
import { GuideModal } from '../../ui/guide-modal';
import { MetricTile } from '../../ui/metric-tile';
import { RagBadge } from '../../ui/rag-badge';

/**
 * Shift-left Rollout - how far a project has moved from reporting on evidence to enforcing it
 * where work happens (docs/PROPOSAL-ShiftLeft-Pivot.md).
 *
 * The stage is a recorded decision; whether it may change arrives from the API as a list of
 * criteria. Nothing here decides a status, and every write is authorized server-side - the
 * buttons are offered to everyone and the API says no.
 */
@Component({
  selector: 'sl-rollout',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, MetricTile, RagBadge, FreshnessStrip, GuideModal, Chart],
  templateUrl: './rollout.html',
  styleUrl: './rollout.css',
})
export class RolloutPage {
  private readonly api = inject(Api);

  readonly projectId = input.required<string>();
  /** Cross-link into the evidence record the engine evaluates. */
  readonly openEvidence = output<void>();

  readonly openGuide = signal(false);
  readonly guide = signal<PerspectiveGuide | null>(null);
  readonly error = signal<string | null>(null);
  readonly busy = signal(false);
  /** Announced politely, so a stage change or a refusal is never a silent visual change. */
  readonly announcement = signal('');
  readonly refusal = signal<Refusal | null>(null);
  readonly rollbackOpen = signal(false);
  readonly rollbackNote = signal('');

  private readonly override = signal<RolloutBoard | null>(null);

  private readonly fetched = toSignal(
    toObservable(computed(() => this.projectId())).pipe(
      switchMap((id) =>
        this.api.rollout(id).pipe(
          catchError((err) => {
            this.error.set(
              errorMessage(err, 'This project is not enrolled in the rollout. That is a gap, not a pass.'),
            );
            return of(null as RolloutBoard | null);
          }),
        ),
      ),
    ),
    { initialValue: null },
  );

  /** A write returns the recomputed board; until then the fetched one stands. */
  readonly data = computed(() => this.override() ?? this.fetched());

  readonly current = computed(() => this.data()?.stages.find((s) => s.state === 'current') ?? null);
  readonly next = computed(() => {
    const board = this.data();
    return board?.stages.find((s) => s.index === board.stage + 1) ?? null;
  });
  readonly previous = computed(() => {
    const board = this.data();
    return board?.stages.find((s) => s.index === board.stage - 1) ?? null;
  });
  readonly needsSignoff = computed(() => {
    const board = this.data();
    return !!board && board.stage === 1 && !board.signoff.by;
  });
  readonly chart = (key: string) => this.data()?.charts.find((c) => c.key === key) ?? null;

  constructor() {
    effect(() => {
      if (this.fetched()) this.error.set(null);
      // A project switch discards any state that belonged to the project you just left.
      this.projectId();
      this.override.set(null);
      this.refusal.set(null);
      this.rollbackOpen.set(false);
      this.rollbackNote.set('');
    });
  }

  showGuide(): void {
    if (this.guide()) {
      this.openGuide.set(true);
      return;
    }
    this.api.guide('rollout').subscribe({
      next: (guide) => {
        this.guide.set(guide);
        this.openGuide.set(true);
      },
      error: (err) =>
        this.refusal.set(refusal(err, 'The guide for this page could not be loaded.')),
    });
  }

  signoff(): void {
    this.write(this.api.recordRolloutSignoff(this.projectId()), (board) =>
      `Team sign-off recorded by ${board.signoff.by}.`,
    );
  }

  advance(): void {
    this.write(this.api.advanceRollout(this.projectId(), ''), (board) =>
      `${board.project_label} advanced to ${board.stage_label}.`,
    );
  }

  rollback(): void {
    const note = this.rollbackNote().trim();
    if (!note) {
      this.refusal.set({ message: "Say why you're rolling back. It goes in the audit log.", blockers: [] });
      return;
    }
    this.write(this.api.rollbackRollout(this.projectId(), note), (board) => {
      this.rollbackOpen.set(false);
      this.rollbackNote.set('');
      return `${board.project_label} rolled back to ${board.stage_label}.`;
    });
  }

  private write(call: Observable<RolloutBoard>, done: (board: RolloutBoard) => string): void {
    this.busy.set(true);
    this.refusal.set(null);
    call.subscribe({
      next: (board) => {
        this.override.set(board);
        this.busy.set(false);
        this.announcement.set(done(board));
      },
      error: (err) => {
        this.busy.set(false);
        // The API's refusal, in the API's words - including the unmet criteria, as a list.
        const refusal = writeRefusal(err, 'That change was refused.');
        this.refusal.set(refusal);
        this.announcement.set(refusal.message);
      },
    });
  }
}
