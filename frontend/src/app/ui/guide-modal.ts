import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { PerspectiveGuide } from '../core/models';

/**
 * The per-page guide. Organised per widget, because the page level exists only to group:
 * each entry answers the same four questions, and a widget that cannot answer them cannot ship.
 */
@Component({
  selector: 'sl-guide-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'closed.emit()' },
  template: `
    <div class="scrim" (click)="closed.emit()">
      <div class="modal" role="dialog" aria-modal="true" [attr.aria-label]="guide().title"
           (click)="$event.stopPropagation()">
        <header class="head">
          <div class="head-text">
            <div class="label-caps">Widget guide</div>
            <h2>{{ guide().title }}</h2>
            <p class="sub">{{ guide().subtitle }}</p>
          </div>
          <button class="btn" (click)="closed.emit()">Close</button>
        </header>
        <div class="body">
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
      </div>
    </div>
  `,
  styles: [
    `
      .scrim {
        position: fixed; inset: 0; background: rgba(18, 19, 22, 0.5); z-index: 60;
        display: flex; align-items: center; justify-content: center; padding: 32px;
      }
      .modal {
        width: 100%; max-width: 920px; max-height: 86vh; background: var(--surface);
        border-radius: 14px; box-shadow: 0 30px 80px rgba(18, 19, 22, 0.28);
        display: flex; flex-direction: column; overflow: hidden;
      }
      .head {
        padding: 20px 24px 16px; border-bottom: 1px solid var(--border-soft);
        display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
      }
      .head-text { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
      h2 { margin: 0; font-size: 18px; font-weight: 600; letter-spacing: -0.015em; line-height: 1.3; }
      .sub { margin: 0; font-size: 12.5px; color: var(--muted); line-height: 1.55; max-width: 78ch; }
      .body { flex: 1; overflow-y: auto; padding: 18px 24px 32px; display: flex; flex-direction: column; gap: 16px; }
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
      .footnote { margin: 0; font-size: 11.5px; color: var(--faint); line-height: 1.6; }
      @media (max-width: 640px) { dl { grid-template-columns: minmax(0, 1fr); } .scrim { padding: 12px; } }
    `,
  ],
})
export class GuideModal {
  readonly guide = input.required<PerspectiveGuide>();
  readonly closed = output<void>();
}
