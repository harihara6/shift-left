import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

/**
 * The modal shell: scrim, panel, header, scrolling body, footer.
 *
 * One shell so every modal in the app closes the same two ways — scrim click and Escape — at the
 * same size. What goes inside is projected: `[body]` scrolls, `[foot]` stays put.
 */
@Component({
  selector: 'sl-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'closed.emit()' },
  template: `
    <div class="scrim" (click)="closed.emit()">
      <div class="modal" role="dialog" aria-modal="true" [attr.aria-label]="title()"
           (click)="$event.stopPropagation()">
        <header class="head">
          <div class="head-text">
            @if (label()) { <div class="label-caps">{{ label() }}</div> }
            <h2>{{ title() }}</h2>
            @if (sub()) { <p class="sub">{{ sub() }}</p> }
          </div>
          <button class="btn" (click)="closed.emit()">Close</button>
        </header>
        <div class="body"><ng-content select="[body]" /></div>
        <footer class="foot"><ng-content select="[foot]" /></footer>
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
      .body {
        flex: 1; overflow-y: auto; padding: 18px 24px 24px;
        display: flex; flex-direction: column; gap: 16px;
      }
      .foot {
        padding: 14px 24px; border-top: 1px solid var(--border-soft); background: var(--surface-sunken);
        display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
      }
      .foot:empty { display: none; }
      @media (max-width: 640px) { .scrim { padding: 12px; } }
    `,
  ],
})
export class Modal {
  readonly title = input.required<string>();
  readonly label = input('');
  readonly sub = input('');
  readonly closed = output<void>();
}
