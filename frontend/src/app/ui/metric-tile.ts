import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { Tile } from '../core/models';
import { RagBadge } from './rag-badge';

/** A metric tile. Its number is monospaced, its status lists reasons, and it drills down. */
@Component({
  selector: 'sl-tile',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RagBadge],
  template: `
    <div class="tile card">
      <div class="label">{{ tile().label }}</div>
      <div class="value mono" [class.value-good]="tile().status?.rag === 'good'"
           [class.value-watch]="tile().status?.rag === 'watch'"
           [class.value-poor]="tile().status?.rag === 'poor'">
        {{ tile().value }}
      </div>
      <div class="note">{{ tile().note }}</div>
      @if (tile().status; as status) {
        <sl-rag [state]="status" />
        @if (status.reasons.length) {
          <ul class="reasons">
            @for (reason of status.reasons; track reason) { <li>{{ reason }}</li> }
          </ul>
        }
      }
      @if (tile().drill; as drill) {
        <a class="drill" [href]="drill.url" target="_blank" rel="noopener">{{ drill.label }} ↗</a>
      } @else {
        <!-- No source link means the number is a claim, not a signal. Say so rather than hide it. -->
        <span class="no-drill">No source link — connector not configured</span>
      }
    </div>
  `,
  styles: [
    `
      .tile { padding: 14px 16px; display: flex; flex-direction: column; gap: 5px; height: 100%; }
      .label { font-size: 11.5px; color: var(--muted); }
      .value { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; }
      .value-good { color: var(--good); }
      .value-watch { color: var(--watch); }
      .value-poor { color: var(--poor); }
      .note { font-size: 11px; color: var(--faint); line-height: 1.45; }
      .reasons { margin: 2px 0 0; padding-left: 14px; font-size: 11px; color: var(--muted); line-height: 1.5; }
      .drill { font-size: 11px; margin-top: auto; padding-top: 6px; }
      .no-drill { font-size: 11px; color: var(--faint); margin-top: auto; padding-top: 6px; }
    `,
  ],
})
export class MetricTile {
  readonly tile = input.required<Tile>();
}
