import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { RagState } from '../core/models';

/**
 * A RAG state, rendered as colour *and* shape.
 *
 * The prototype's dots were colour-only, which fails WCAG 2.2 AA - a tool that reports on
 * accessibility compliance has to meet it. The glyph carries the same meaning as the colour.
 */
@Component({
  selector: 'sl-rag',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="rag" [style.color]="color()" [title]="tooltip()">
      <svg class="glyph" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
        <circle cx="6" cy="6" r="5.5" [attr.fill]="bg()" [attr.stroke]="color()" stroke-width="1" />
        @switch (state().glyph) {
          @case ('check') { <path d="M3.4 6.2 5.2 8l3.4-3.6" fill="none" [attr.stroke]="color()" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /> }
          @case ('alert') { <path d="M6 3.1v3.6M6 8.6v.5" fill="none" [attr.stroke]="color()" stroke-width="1.6" stroke-linecap="round" /> }
          @case ('cross') { <path d="M4 4l4 4M8 4l-4 4" fill="none" [attr.stroke]="color()" stroke-width="1.6" stroke-linecap="round" /> }
          @case ('dash') { <path d="M3.6 6h4.8" fill="none" [attr.stroke]="color()" stroke-width="1.6" stroke-linecap="round" /> }
          @default { <path d="M4.4 4.6a1.6 1.6 0 1 1 1.9 1.9v.8M6 9.1v.4" fill="none" [attr.stroke]="color()" stroke-width="1.4" stroke-linecap="round" /> }
        }
      </svg>
      @if (showLabel()) {
        <span class="text">{{ state().label }}</span>
      }
    </span>
  `,
  styles: [
    `
      .rag { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
      .glyph { width: 12px; height: 12px; flex-shrink: 0; }
      .text { white-space: nowrap; }
    `,
  ],
})
export class RagBadge {
  readonly state = input.required<RagState>();
  readonly showLabel = input(true);

  private readonly palette: Record<string, [string, string]> = {
    good: ['var(--good)', 'var(--good-bg)'],
    watch: ['var(--watch)', 'var(--watch-bg)'],
    poor: ['var(--poor)', 'var(--poor-bg)'],
    neutral: ['var(--neutral)', 'var(--neutral-bg)'],
    missing: ['var(--missing)', 'var(--missing-bg)'],
  };

  readonly color = computed(() => this.palette[this.state().rag][0]);
  readonly bg = computed(() => this.palette[this.state().rag][1]);
  /** The reasons are the status. They are never collapsed away into a colour. */
  readonly tooltip = computed(() => this.state().reasons.join(' · '));
}
