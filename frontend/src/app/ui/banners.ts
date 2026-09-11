import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { EvidenceLink, Freshness } from '../core/models';

/**
 * The rule from PRD s4.1, made structural rather than documented: a flow view says out loud
 * that it is not evidence, and carries the link to the record that governs.
 */
@Component({
  selector: 'sl-flow-banner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="banner">
      <div class="text">
        <span class="tag">Flow telemetry</span>
        <span>{{ link().note }}</span>
      </div>
      <button class="btn" (click)="openEvidence.emit()">{{ link().label }} →</button>
    </div>
  `,
  styles: [
    `
      .banner {
        display: flex; align-items: center; justify-content: space-between; gap: 16px;
        flex-wrap: wrap; background: var(--accent-bg); border: 1px solid var(--accent-border);
        border-radius: 12px; padding: 12px 16px;
      }
      .text { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--ink-2); line-height: 1.55; }
      .tag {
        flex-shrink: 0; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase;
        font-weight: 600; color: var(--accent-hover); background: var(--surface);
        border: 1px solid var(--accent-border); border-radius: 6px; padding: 3px 8px;
      }
    `,
  ],
})
export class FlowBanner {
  readonly link = input.required<EvidenceLink>();
  readonly openEvidence = output<void>();
}

/** Staleness is stated on the page, not buried in a tooltip. Stale never reads as healthy. */
@Component({
  selector: 'sl-freshness',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="strip" [class.stale]="freshness().stale" role="status">
      <span class="dot" aria-hidden="true"></span>
      <span class="msg">
        @if (freshness().stale) {
          {{ freshness().note }}
        } @else {
          All sources within their freshness threshold.
        }
      </span>
      <span class="sources mono">
        @for (connector of freshness().connectors; track connector.key) {
          <span class="source" [class.source-stale]="connector.stale">
            {{ connector.name }}
            @if (connector.missing) { · never synced } @else { · {{ connector.age_minutes }}m }
          </span>
        }
      </span>
    </div>
  `,
  styles: [
    `
      .strip {
        display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
        background: var(--good-bg); border: 1px solid #cfe6da; border-radius: 10px;
        padding: 9px 14px; font-size: 12px; color: var(--good);
      }
      .strip.stale { background: var(--watch-bg); border-color: #eddcb8; color: var(--watch); }
      .dot { width: 7px; height: 7px; border-radius: 99px; background: currentColor; flex-shrink: 0; }
      .msg { flex: 1; min-width: 220px; line-height: 1.5; }
      .sources { display: flex; gap: 12px; flex-wrap: wrap; font-size: 11px; color: var(--muted); }
      .source-stale { color: var(--watch); font-weight: 500; }
    `,
  ],
})
export class FreshnessStrip {
  readonly freshness = input.required<Freshness>();
}
