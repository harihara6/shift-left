import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { Api } from '../../core/api';
import { errorMessage, writeRefusal } from '../../core/errors';
import { KickoffSettings, KickoffSettingsWrite } from '../../core/models';

/**
 * Service-wide Feature Kickoff defaults.
 *
 * These are what a new analysis starts filled in with, so the loop from a requirement to a backlog
 * doesn't begin by retyping the same template link, backlog and labels every time. They are
 * defaults, never a lock: each one stays editable on the analysis, and changing them here never
 * reaches an analysis already under way.
 *
 * Readable by anyone — no credential is stored here — and writable only by a platform admin, which
 * the API decides. This page renders that answer rather than deciding it.
 */
@Component({
  selector: 'sl-kickoff-tab',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DatePipe],
  templateUrl: './kickoff-tab.html',
  styleUrl: './settings.css',
})
export class KickoffTab {
  private readonly api = inject(Api);

  readonly settings = signal<KickoffSettings | null>(null);
  readonly draft = signal<KickoffSettingsWrite | null>(null);
  readonly notice = signal('');
  readonly saving = signal(false);

  readonly editable = computed(() => this.settings()?.editable ?? false);
  readonly sections = computed(() => this.settings()?.section_catalog ?? []);
  readonly dirty = computed(
    () => JSON.stringify(this.draft()) !== JSON.stringify(this.asWrite(this.settings())),
  );

  constructor() {
    this.load();
  }

  private asWrite(s: KickoffSettings | null): KickoffSettingsWrite | null {
    if (!s) return null;
    return {
      tdd_template_url: s.tdd_template_url,
      tdd_space_key: s.tdd_space_key,
      tdd_parent_url: s.tdd_parent_url,
      tdd_sections: [...s.tdd_sections],
      jira_project_url: s.jira_project_url,
      jira_defaults: { ...s.jira_defaults },
      analysis_prompt: s.analysis_prompt,
      tdd_prompt: s.tdd_prompt,
    };
  }

  private load(): void {
    this.api.kickoffSettings().subscribe({
      next: (settings) => {
        this.settings.set(settings);
        this.draft.set(this.asWrite(settings));
      },
      error: (err) => this.notice.set(errorMessage(err, 'The defaults could not be loaded.')),
    });
  }

  patch<K extends keyof KickoffSettingsWrite>(key: K, value: KickoffSettingsWrite[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  jira<K extends keyof KickoffSettingsWrite['jira_defaults']>(key: K): string {
    const value = this.draft()?.jira_defaults[key];
    return Array.isArray(value) ? value.join(', ') : String(value ?? '');
  }

  setJira(key: keyof KickoffSettingsWrite['jira_defaults'], value: string): void {
    const list = key === 'labels' || key === 'components';
    const next = list ? value.split(',').map((v) => v.trim()).filter(Boolean) : value.trim();
    this.draft.update((d) => (d ? { ...d, jira_defaults: { ...d.jira_defaults, [key]: next } } : d));
  }

  ticked(key: string): boolean {
    return this.draft()?.tdd_sections.includes(key) ?? false;
  }

  toggleSection(key: string): void {
    const current = this.draft()?.tdd_sections ?? [];
    // Kept in catalogue order, so the ticks read the same way the document does.
    const wanted = new Set(current.includes(key) ? current.filter((k) => k !== key) : [...current, key]);
    this.patch('tdd_sections', this.sections().map((s) => s.key).filter((k) => wanted.has(k)));
  }

  tickRecommended(): void {
    this.patch('tdd_sections', this.sections().filter((s) => s.default).map((s) => s.key));
  }

  revert(): void {
    this.draft.set(this.asWrite(this.settings()));
    this.notice.set('');
  }

  save(): void {
    const body = this.draft();
    if (!body) return;
    this.saving.set(true);
    this.api.saveKickoffSettings(body).subscribe({
      next: (settings) => {
        this.settings.set(settings);
        this.draft.set(this.asWrite(settings));
        this.saving.set(false);
        this.notice.set('Saved. New analyses start from these; anything already under way is unchanged.');
      },
      error: (err) => {
        this.saving.set(false);
        this.notice.set(writeRefusal(err, errorMessage(err, 'The defaults were not saved.')).message);
      },
    });
  }
}
