import { Injectable, computed, signal } from '@angular/core';

import { PeriodSelection } from './models';

const STORAGE_KEY = 'shiftleft.period-selection';

const DEFAULT: PeriodSelection = { granularity: 'quarter', preset: 'previous' };

/**
 * The page's reporting window, held in one place because the filter sits in the header and
 * governs everything below it.
 *
 * The default is deliberately relative — the current period against the one before it — so the
 * page is never pinned to a quarter that will go stale. A custom range is remembered for the
 * session; the relative default is what comes back on a fresh load.
 */
@Injectable({ providedIn: 'root' })
export class PeriodStore {
  private readonly state = signal<PeriodSelection>(this.restore());

  readonly selection = this.state.asReadonly();
  readonly granularity = computed(() => this.state().granularity);
  readonly preset = computed(() => this.state().preset);

  setGranularity(granularity: string): void {
    // Changing granularity drops any explicit period: Q3-2026 is not a half or a year.
    this.apply({ granularity, preset: this.state().preset === 'custom' ? 'previous' : this.state().preset });
  }

  setPreset(preset: string): void {
    if (preset === 'custom') {
      this.apply({ ...this.state(), preset });
      return;
    }
    this.apply({ granularity: this.state().granularity, preset });
  }

  setCustom(period: string, baseline: string): void {
    this.apply({ granularity: this.state().granularity, preset: 'custom', period, baseline });
  }

  reset(): void {
    this.apply(DEFAULT);
  }

  private apply(selection: PeriodSelection): void {
    this.state.set(selection);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
    } catch {
      // Storage being unavailable is not a reason to break the page.
    }
  }

  private restore(): PeriodSelection {
    try {
      const stored = sessionStorage.getItem(STORAGE_KEY);
      if (!stored) return DEFAULT;
      const parsed = JSON.parse(stored) as PeriodSelection;
      return parsed.granularity && parsed.preset ? parsed : DEFAULT;
    } catch {
      return DEFAULT;
    }
  }
}
