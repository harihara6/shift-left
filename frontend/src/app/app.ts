import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from './core/api';
import { errorMessage } from './core/errors';
import { Comparison, FilterOptions, ProjectSummary, WhoAmI } from './core/models';
import { PeriodStore } from './core/period-store';
import { Session } from './core/session';
import { PeriodFilter } from './ui/period-filter';
import { FeatureReadinessPage } from './pages/feature-readiness/feature-readiness';
import { KickoffPage } from './pages/kickoff/kickoff';
import { RolloutPage } from './pages/rollout/rollout';
import { Settings } from './pages/settings/settings';
import { TeamInsights } from './pages/team-insights/team-insights';

/** The six perspectives, in the order the PRD ranks them. Evidence is first, and it is first
 *  for a reason: every flow view links back into it. */
const NAV = [
  {
    group: 'Evidence',
    items: [
      // Where a feature starts: a PRD taken to a checked, tagged plan before any work begins.
      { key: 'kickoff', label: 'Feature Kickoff', built: true },
      { key: 'discipline', label: 'Feature Readiness', built: true },
      // Where the evidence engine shows up at the point of work, and whether it is trusted there.
      { key: 'rollout', label: 'Shift-left Rollout', built: true },
    ],
  },
  {
    group: 'Flow',
    items: [
      { key: 'execution', label: 'Developer & SDET Flow', built: false },
      { key: 'delivery', label: 'Team Insights', built: true },
    ],
  },
  {
    group: 'Confidence',
    items: [
      { key: 'release', label: 'Release Readiness', built: false },
      { key: 'portfolio', label: 'Portfolio & Programme', built: false },
      { key: 'signal', label: 'Quality Trajectory', built: false },
    ],
  },
  {
    group: 'Administration',
    items: [{ key: 'settings', label: 'Settings', built: true }],
  },
];

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TeamInsights, FeatureReadinessPage, KickoffPage, RolloutPage, Settings, PeriodFilter],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private readonly api = inject(Api);
  readonly session = inject(Session);
  readonly periods = inject(PeriodStore);

  readonly nav = NAV;
  readonly screen = signal<string>('delivery');
  readonly projects = signal<ProjectSummary[]>([]);
  readonly projectId = signal<string>('');
  readonly filterOptions = signal<FilterOptions | null>(null);
  readonly comparison = signal<Comparison | null>(null);
  /** Who the API says is calling. In a production build this is the only identity shown. */
  readonly me = signal<WhoAmI | null>(null);
  readonly loadError = signal<string | null>(null);
  /** False until the first answer about projects, so an empty state never flashes while loading. */
  readonly projectsLoaded = signal(false);
  /** Set once the person picks a screen; until then an empty install opens on Settings. */
  private chosen = false;

  /** Perspectives that report over a window. Settings does not, so the filter stays hidden there. */
  private readonly PERIODIC = new Set(['delivery', 'execution', 'release', 'signal']);
  readonly showPeriodFilter = computed(() => this.PERIODIC.has(this.screen()) && !!this.projectId());

  readonly currentProject = computed(() =>
    this.projects().find((p) => p.id === this.projectId()) ?? null,
  );

  readonly perspectiveLabel = computed(() => {
    const item = NAV.flatMap((group) => group.items).find((i) => i.key === this.screen());
    return item?.label ?? '';
  });

  constructor() {
    this.loadProjects();
    effect(() => this.loadPeriodOptions(this.projectId()));
  }

  /** `select` picks a project after it changes (one just created in Settings, say). */
  loadProjects(select?: string): void {
    this.api.me().subscribe({
      next: (me) => this.me.set(me),
      error: () => this.me.set(null),
    });
    this.api.projects().subscribe({
      next: (projects) => {
        this.loadError.set(null);
        this.projects.set(projects);
        this.projectsLoaded.set(true);
        const keep = select ?? this.projectId();
        this.projectId.set(projects.some((p) => p.id === keep) ? keep : (projects[0]?.id ?? ''));
        // Nothing to report on yet: the first useful screen is the one that sets a project up.
        if (!projects.length && !this.chosen) this.screen.set('settings');
      },
      error: (err) => {
        this.projects.set([]);
        this.projectId.set('');
        this.projectsLoaded.set(true);
        this.loadError.set(errorMessage(err, 'Your projects could not be loaded.'));
      },
    });
  }

  /** The filter's options are per project — each has its own history of snapshots. */
  private loadPeriodOptions(projectId: string): void {
    if (!projectId) {
      this.filterOptions.set(null);
      return;
    }
    this.api.periodOptions(projectId).subscribe({
      next: (options) => this.filterOptions.set(options),
      error: () => this.filterOptions.set(null),
    });
  }

  go(key: string, built: boolean): void {
    if (!built) return;
    this.chosen = true;
    this.screen.set(key);
  }

  switchIdentity(email: string): void {
    this.session.use(email);
    // What this caller may see changes with them - reload rather than show a stale list.
    this.loadProjects();
    this.screen.set(this.screen());
  }
}
