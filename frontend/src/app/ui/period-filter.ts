import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';

import { Comparison, FilterOptions, Period } from '../core/models';
import { PeriodStore } from '../core/period-store';

/**
 * The reporting window for the whole page.
 *
 * Defaults to the current period against the one before it, at quarter granularity, and never
 * names a fixed quarter. Beyond that it offers the two comparisons people actually reach for:
 * the preceding period, and the same period a year ago — the second being the one that survives
 * seasonality. A custom range is there for everything else.
 */
@Component({
  selector: 'sl-period-filter',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'open.set(false)' },
  template: `
    <div class="filter">
      <button class="trigger" [class.open]="open()" [attr.aria-expanded]="open()"
              aria-haspopup="dialog" (click)="open.set(!open())">
        <span class="trigger-label">
          <span class="label-caps">Reporting window</span>
          <span class="trigger-value">
            @if (comparison(); as c) {
              <span class="mono">{{ c.current.label }}</span>
              <span class="vs">vs</span>
              <span class="mono">{{ c.baseline.label }}</span>
            } @else {
              <span class="mono">Loading…</span>
            }
          </span>
        </span>
        <span class="chevron" aria-hidden="true">{{ open() ? '▴' : '▾' }}</span>
      </button>

      @if (open()) {
        <div class="scrim" (click)="open.set(false)"></div>
        <div class="popover" role="dialog" aria-label="Reporting window">
          <fieldset class="group">
            <legend class="label-caps">Compare by</legend>
            <div class="segmented">
              @for (option of options()?.granularities ?? []; track option.key) {
                <button class="segment" [class.on]="option.key === store.granularity()"
                        [attr.aria-pressed]="option.key === store.granularity()"
                        (click)="store.setGranularity(option.key)">{{ option.label }}</button>
              }
            </div>
          </fieldset>

          <fieldset class="group">
            <legend class="label-caps">Against</legend>
            @for (preset of options()?.presets ?? []; track preset.key) {
              <button class="choice" [class.on]="preset.key === store.preset()"
                      [attr.aria-pressed]="preset.key === store.preset()"
                      (click)="store.setPreset(preset.key)">
                <span class="radio"></span>
                <span>{{ preset.label }}</span>
                @if (preset.key !== 'custom' && previewFor(preset.key); as preview) {
                  <span class="preview mono">{{ preview }}</span>
                }
              </button>
            }
          </fieldset>

          @if (store.preset() === 'custom') {
            <fieldset class="group">
              <legend class="label-caps">Custom range</legend>
              <label class="picker">
                <span>Report on</span>
                <select [value]="customCurrent()" (change)="pickCurrent($any($event.target).value)">
                  @for (period of periodList(); track period.key) {
                    <option [value]="period.key" [disabled]="!period.has_data">
                      {{ period.label }}{{ period.has_data ? '' : ' — no data' }}
                    </option>
                  }
                </select>
              </label>
              <label class="picker">
                <span>Compare against</span>
                <select [value]="customBaseline()" (change)="pickBaseline($any($event.target).value)">
                  @for (period of periodList(); track period.key) {
                    <option [value]="period.key" [disabled]="!period.has_data">
                      {{ period.label }}{{ period.has_data ? '' : ' — no data' }}
                    </option>
                  }
                </select>
              </label>
            </fieldset>
          }

          @if (comparison(); as c) {
            <p class="caveat" [class.warn]="!c.comparable_lengths">{{ c.caveat }}</p>
            @if (!c.current.complete) {
              <p class="note">
                {{ c.current.label }} is still in progress — {{ c.current.weeks }} weeks of data so far.
              </p>
            }
            @if (c.aggregated) {
              <p class="note">Built from {{ c.covered_periods.join(', ') }}.</p>
            }
          }
          <p class="note">Data through {{ options()?.data_through ?? '—' }}.</p>

          <div class="popover-actions">
            <button class="btn" (click)="store.reset()">Reset to default</button>
            <button class="btn btn-primary" (click)="open.set(false)">Done</button>
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .filter { position: relative; }
      .trigger {
        display: flex; align-items: center; gap: 12px; background: var(--surface);
        border: 1px solid var(--border); border-radius: 10px; padding: 7px 12px; cursor: pointer;
        text-align: left;
      }
      .trigger:hover, .trigger.open { border-color: var(--accent); }
      .trigger-label { display: flex; flex-direction: column; gap: 2px; }
      .trigger-value { display: flex; align-items: baseline; gap: 6px; font-size: 13px; color: var(--ink); }
      .vs { font-size: 11px; color: var(--faint); }
      .chevron { color: var(--faint); font-size: 10px; }

      .scrim { position: fixed; inset: 0; z-index: 40; }
      .popover {
        position: absolute; top: calc(100% + 8px); right: 0; z-index: 41; width: 340px;
        background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
        box-shadow: 0 18px 48px rgba(18, 19, 22, 0.16); padding: 16px;
        display: flex; flex-direction: column; gap: 14px;
      }
      .group { border: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
      legend { padding: 0; }

      .segmented { display: flex; gap: 4px; background: var(--surface-sunken); border-radius: 8px; padding: 3px; }
      .segment {
        flex: 1; background: transparent; border: none; border-radius: 6px; padding: 6px 8px;
        font-size: 12.5px; color: var(--muted); cursor: pointer;
      }
      .segment.on { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(18, 19, 22, 0.1); font-weight: 500; }

      .choice {
        display: flex; align-items: center; gap: 9px; width: 100%; text-align: left;
        background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        padding: 9px 11px; font-size: 12.5px; color: var(--ink-2); cursor: pointer;
      }
      .choice.on { border-color: var(--accent); background: var(--accent-bg); color: var(--accent-hover); }
      .radio { width: 12px; height: 12px; border-radius: 99px; border: 1.5px solid var(--faint); flex-shrink: 0; }
      .choice.on .radio { border-color: var(--accent); border-width: 4px; }
      .preview { margin-left: auto; font-size: 11px; color: var(--faint); }
      .choice.on .preview { color: var(--accent-hover); }

      .picker { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12.5px; color: var(--muted); }
      .picker select { width: 58%; }

      .caveat {
        margin: 0; font-size: 11.5px; line-height: 1.55; color: var(--good);
        background: var(--good-bg); border: 1px solid #cfe6da; border-radius: 8px; padding: 8px 10px;
      }
      .caveat.warn { color: var(--watch); background: var(--watch-bg); border-color: #eddcb8; }
      .note { margin: 0; font-size: 11px; color: var(--faint); line-height: 1.5; }
      .popover-actions { display: flex; gap: 8px; justify-content: flex-end; }

      @media (max-width: 640px) {
        .popover { width: min(340px, calc(100vw - 32px)); right: auto; left: 0; }
      }
    `,
  ],
})
export class PeriodFilter {
  readonly store = inject(PeriodStore);

  readonly options = input<FilterOptions | null>(null);
  readonly comparison = input<Comparison | null>(null);

  readonly open = signal(false);

  readonly periodList = computed<Period[]>(
    () => this.options()?.periods[this.store.granularity()] ?? [],
  );

  /** Shows what each preset would resolve to, so the choice is made with its answer visible. */
  previewFor(preset: string): string | null {
    const periods = this.periodList();
    if (!periods.length) return null;
    const head = periods[0];
    if (preset === 'previous') return periods[1] ? `${head.label} vs ${periods[1].label}` : null;
    if (preset === 'last_year') {
      const perYear = { quarter: 4, half: 2, year: 1 }[this.store.granularity()] ?? 4;
      const target = periods[perYear];
      return target ? `${head.label} vs ${target.label}` : null;
    }
    return null;
  }

  readonly customCurrent = computed(
    () => this.store.selection().period ?? this.comparison()?.current.key ?? '',
  );
  readonly customBaseline = computed(
    () => this.store.selection().baseline ?? this.comparison()?.baseline.key ?? '',
  );

  pickCurrent(key: string): void {
    this.store.setCustom(key, this.customBaseline());
  }

  pickBaseline(key: string): void {
    this.store.setCustom(this.customCurrent(), key);
  }
}
