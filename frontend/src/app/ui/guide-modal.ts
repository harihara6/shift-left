import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { PerspectiveGuide } from '../core/models';
import { Modal } from './modal';

/**
 * The per-page guide. Organised per widget, because the page level exists only to group:
 * each entry answers the same four questions, and a widget that cannot answer them cannot ship.
 *
 * The scrim, panel and header come from `sl-modal`, so every modal in the app closes the same two
 * ways at the same size. Only what goes inside is this component's own.
 */
@Component({
  selector: 'sl-guide-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Modal],
  template: `
    <sl-modal label="Widget guide" [title]="guide().title" [sub]="guide().subtitle"
              (closed)="closed.emit()">
      <div body>
        <section class="who">
          <div class="label-caps">Useful if you are</div>
          @for (line of guide().audience; track line) {
            <div class="who-row"><span class="dash">—</span><span>{{ line }}</span></div>
          }
        </section>
        @for (widget of guide().widgets; track widget.widget_key; let i = $index) {
          <section class="widget">
            <header class="widget-head">
              <span class="mono num">{{ i + 1 }}</span>
              <span class="card-title">{{ widget.widget }}</span>
            </header>
            <dl>
              <dt class="label-caps">Decision</dt><dd>{{ widget.decision }}</dd>
              <dt class="label-caps">Where it comes from</dt><dd>{{ widget.source }}</dd>
              <dt class="label-caps">How it is fetched</dt><dd class="mono code">{{ widget.fetch }}</dd>
              <dt class="label-caps">Tag it at source</dt><dd>{{ widget.tagging }}</dd>
            </dl>
          </section>
        }
        <p class="footnote">{{ guide().footnote }}</p>
      </div>
    </sl-modal>
  `,
  styles: [
    `
      /* Scrollable flex column: children must not compress instead of the container scrolling. */
      .who, .widget { flex: 0 0 auto; border: 1px solid var(--border-soft); border-radius: 12px; }
      .who { background: var(--surface-sunken); padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
      .who-row { display: flex; gap: 9px; font-size: 12.5px; color: var(--ink-2); line-height: 1.6; }
      .dash { color: var(--accent); }
      .widget { overflow: hidden; }
      .widget-head {
        display: flex; align-items: center; gap: 10px; padding: 12px 16px;
        background: var(--surface-sunken); border-bottom: 1px solid var(--border-soft);
      }
      .num { font-size: 11px; color: var(--faint); }
      dl { margin: 0; padding: 14px 16px; display: grid; grid-template-columns: minmax(0, 150px) minmax(0, 1fr); gap: 12px 16px; }
      dt { padding-top: 2px; }
      dd { margin: 0; font-size: 12.5px; color: var(--ink-2); line-height: 1.6; }
      .code { font-size: 11.5px; background: var(--surface-sunken); border: 1px solid var(--border-soft); border-radius: 8px; padding: 8px 10px; overflow-wrap: anywhere; }
      .footnote { flex: 0 0 auto; margin: 0; font-size: 11.5px; color: var(--faint); line-height: 1.6; }
      @media (max-width: 640px) { dl { grid-template-columns: minmax(0, 1fr); } }
    `,
  ],
})
export class GuideModal {
  readonly guide = input.required<PerspectiveGuide>();
  readonly closed = output<void>();
}
