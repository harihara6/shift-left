import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../../core/api';
import { errorMessage, writeRefusal } from '../../core/errors';
import {
  AccessGrant,
  OnboardingResult,
  ProjectDetail,
  ProjectSummary,
  ProjectTemplate,
  QueryPreview,
} from '../../core/models';
import { OnboardingWizard } from './onboarding-wizard';

@Component({
  selector: 'sl-projects-tab',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, OnboardingWizard],
  templateUrl: './projects-tab.html',
  styleUrl: './settings.css',
})
export class ProjectsTab {
  private readonly api = inject(Api);

  readonly projects = signal<ProjectSummary[]>([]);
  readonly selected = signal<ProjectDetail | null>(null);
  readonly templates = signal<ProjectTemplate[]>([]);
  readonly grants = signal<AccessGrant[]>([]);
  readonly expanded = signal<string | null>(null);
  readonly previews = signal<Record<number, QueryPreview>>({});
  readonly notice = signal<string>('');
  readonly busy = signal(false);

  readonly creating = signal(false);
  /** The guided path. The manual form below it always stays available. */
  readonly guiding = signal(false);
  readonly draft = signal({ key: '', name: '', owner: '' });
  readonly grantDraft = signal({ principal: '', role: 'viewer', via: 'SSO group' });
  readonly addingGrant = signal(false);
  readonly renaming = signal(false);
  readonly renameDraft = signal('');

  readonly roles = ['viewer', 'contributor', 'admin'];
  readonly sources = ['SSO group', 'Explicit grant'];

  /** Every enabled template is one dashboard on this project. */
  readonly enabledCount = computed(() => this.templates().filter((t) => t.enabled).length);

  constructor() {
    this.load();
  }

  private load(selectId?: string): void {
    this.api.projects().subscribe({
      next: (projects) => {
        this.projects.set(projects);
        const next = projects.find((p) => p.id === selectId) ?? projects[0];
        if (next) this.select(next.id);
        else this.selected.set(null);
      },
      error: (err) => this.notice.set(errorMessage(err, 'Your projects could not be loaded.')),
    });
  }

  select(id: string): void {
    this.api.project(id).subscribe({
      next: (detail) => {
        this.selected.set(detail);
        this.grants.set(detail.access);
        this.previews.set({});
      },
      error: (err) => this.notice.set(errorMessage(err, 'That project could not be loaded.')),
    });
    this.api.templates(id).subscribe({
      next: (templates) => this.templates.set(templates),
      error: (err) => this.notice.set(errorMessage(err, "This project's templates could not be loaded.")),
    });
  }

  /** A guided setup is an ordinary project once accepted — from here on it is just a project. */
  onGuidedCreate(result: OnboardingResult): void {
    this.guiding.set(false);
    this.notice.set(result.note);
    this.load(result.project.id);
  }

  createProject(): void {
    const draft = this.draft();
    if (!draft.key || !draft.name || !draft.owner) return;
    this.busy.set(true);
    this.api.createProject(draft).subscribe({
      next: (project) => {
        this.busy.set(false);
        this.creating.set(false);
        this.draft.set({ key: '', name: '', owner: '' });
        this.notice.set(`Created ${project.name}. You are its admin — grant access to anyone else who needs it.`);
        this.load(project.id);
      },
      error: (err) => {
        this.busy.set(false);
        this.notice.set(errorMessage(err, 'Could not create the project.'));
      },
    });
  }

  rename(project: ProjectDetail, name: string): void {
    this.renaming.set(false);
    if (!name.trim() || name === project.name) return;
    this.api.renameProject(project.id, name.trim()).subscribe({
      next: () => this.load(project.id),
      error: (err) => this.notice.set(writeRefusal(err, 'Could not rename the project.').message),
    });
  }

  duplicate(project: ProjectDetail): void {
    this.api.duplicateProject(project.id).subscribe({
      next: (copy) => {
        this.notice.set(
          `Duplicated into ${copy.name}. Templates and their bindings were copied; access grants were not — who may see a new project is always an explicit decision.`,
        );
        this.load(copy.id);
      },
      error: (err) => this.notice.set(writeRefusal(err, 'Could not duplicate the project.').message),
    });
  }

  archive(project: ProjectDetail): void {
    this.api.archiveProject(project.id).subscribe({
      next: () => {
        this.notice.set(`${project.name} archived. Its dashboards are hidden; the audit trail is kept.`);
        this.load();
      },
      error: (err) => this.notice.set(writeRefusal(err, 'Could not archive the project.').message),
    });
  }

  toggleTemplate(template: ProjectTemplate, enabled: boolean): void {
    const project = this.selected();
    if (!project) return;
    this.api.toggleTemplate(project.id, template.template_key, enabled).subscribe({
      next: () => {
        this.notice.set(
          enabled
            ? `${template.name} deep-copied into ${project.name}. Later edits to the catalog template never reach it.`
            : `${template.name} disabled. Its bindings are kept, so re-enabling restores your edits.`,
        );
        this.select(project.id);
      },
      error: (err) => this.notice.set(writeRefusal(err, 'Could not change the template.').message),
    });
  }

  expand(key: string): void {
    this.expanded.update((current) => (current === key ? null : key));
  }

  saveQuery(widgetId: number, query: string): void {
    const project = this.selected();
    if (!project) return;
    this.api.updateBinding(project.id, widgetId, { query }).subscribe({
      next: () => this.notice.set('Query saved to this project only.'),
      error: (err) => this.notice.set(writeRefusal(err, 'Could not save the query.').message),
    });
  }

  preview(widgetId: number): void {
    const project = this.selected();
    if (!project) return;
    this.api.previewBinding(project.id, widgetId).subscribe({
      next: (result) => this.previews.update((all) => ({ ...all, [widgetId]: result })),
      error: (err) => this.notice.set(writeRefusal(err, 'Could not preview the query.').message),
    });
  }

  addGrant(): void {
    const project = this.selected();
    const draft = this.grantDraft();
    if (!project || !draft.principal.trim()) return;
    this.api.addGrant(project.id, { ...draft, principal: draft.principal.trim() }).subscribe({
      next: () => {
        this.grantDraft.set({ principal: '', role: 'viewer', via: 'SSO group' });
        this.addingGrant.set(false);
        this.notice.set('Grant added and written to the audit log.');
        this.select(project.id);
      },
      error: (err) => this.notice.set(writeRefusal(err, 'Could not add the grant.').message),
    });
  }

  revoke(grant: AccessGrant): void {
    const project = this.selected();
    if (!project) return;
    this.api.revokeGrant(project.id, grant.id).subscribe({
      next: () => {
        this.notice.set(`Access revoked for ${grant.principal}.`);
        this.select(project.id);
      },
      error: (err) => this.notice.set(writeRefusal(err, 'Could not revoke the grant.').message),
    });
  }

  previewFor(widgetId: number): QueryPreview | undefined {
    return this.previews()[widgetId];
  }

  keysOf(row: Record<string, unknown>): string[] {
    return Object.keys(row);
  }
}
