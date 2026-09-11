import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';

import { Api } from '../../core/api';
import { PerspectiveGuide } from '../../core/models';
import { GuideModal } from '../../ui/guide-modal';
import { AccessTab } from './access-tab';
import { ConnectorsTab } from './connectors-tab';
import { ProjectsTab } from './projects-tab';

type Tab = 'projects' | 'connectors' | 'access';

@Component({
  selector: 'sl-settings',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ProjectsTab, ConnectorsTab, AccessTab, GuideModal],
  template: `
    <div class="settings">
      <nav class="tabs" aria-label="Settings sections">
        @for (tab of tabs; track tab.key) {
          <button class="tab" [class.active]="tab.key === active()"
                  [attr.aria-current]="tab.key === active() ? 'page' : null"
                  (click)="active.set(tab.key)">{{ tab.label }}</button>
        }
        <button class="btn guide-btn" (click)="showGuide()">How this page works</button>
      </nav>

      @switch (active()) {
        @case ('projects') { <sl-projects-tab /> }
        @case ('connectors') { <sl-connectors-tab /> }
        @case ('access') { <sl-access-tab /> }
      }
    </div>

    @if (openGuide() && guide()) {
      <sl-guide-modal [guide]="guide()!" (closed)="openGuide.set(false)" />
    }
  `,
  styles: [
    `
      .settings { display: flex; flex-direction: column; gap: 20px; }
      .tabs { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
      .tab {
        background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        padding: 7px 14px; font-size: 12.5px; color: var(--ink-2); cursor: pointer;
      }
      .tab:hover { border-color: var(--accent-border); }
      .tab.active { background: var(--rail); border-color: var(--rail); color: #fff; }
      .guide-btn { margin-left: auto; }
    `,
  ],
})
export class Settings {
  private readonly api = inject(Api);

  readonly tabs: { key: Tab; label: string }[] = [
    { key: 'projects', label: 'Projects' },
    { key: 'connectors', label: 'Connectors' },
    { key: 'access', label: 'Access & SSO' },
  ];

  readonly active = signal<Tab>('projects');
  readonly openGuide = signal(false);
  readonly guide = signal<PerspectiveGuide | null>(null);

  showGuide(): void {
    if (this.guide()) {
      this.openGuide.set(true);
      return;
    }
    this.api.guide('settings').subscribe({
      next: (guide) => {
        this.guide.set(guide);
        this.openGuide.set(true);
      },
      // Leave the page as it is; the guide button stays available to retry.
      error: () => this.openGuide.set(false),
    });
  }
}
