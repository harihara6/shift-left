import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AccessGrant,
  AccessModelEntry,
  ConnectorDetail,
  ConnectorSummary,
  ActionRecord,
  ConnectorTestResult,
  FeatureReadiness,
  FilterOptions,
  KickoffAnalysis,
  KickoffAnalysisSummary,
  KickoffCatalog,
  BacklogFields,
  JiraTicketDefaults,
  KickoffRunDetail,
  KickoffRunSummary,
  KickoffSettings,
  KickoffSettingsWrite,
  KickoffStatus,
  KickoffTaskInput,
  CustomCompliance,
  PeriodSelection,
  PerspectiveGuide,
  ProjectDetail,
  ProjectSummary,
  OnboardingAccept,
  OnboardingDraft,
  OnboardingResult,
  ProjectTemplate,
  QueryPreview,
  RolloutBoard,
  TeamInsights,
  WhoAmI,
} from './models';

const API = '/api';

@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  projects(): Observable<ProjectSummary[]> {
    return this.http.get<ProjectSummary[]>(`${API}/projects`);
  }

  project(id: string): Observable<ProjectDetail> {
    return this.http.get<ProjectDetail>(`${API}/projects/${id}`);
  }

  createProject(body: { key: string; name: string; owner: string }): Observable<ProjectDetail> {
    return this.http.post<ProjectDetail>(`${API}/projects`, body);
  }

  renameProject(id: string, name: string): Observable<ProjectDetail> {
    return this.http.patch<ProjectDetail>(`${API}/projects/${id}`, { name });
  }

  duplicateProject(id: string): Observable<ProjectDetail> {
    return this.http.post<ProjectDetail>(`${API}/projects/${id}/duplicate`, {});
  }

  archiveProject(id: string): Observable<void> {
    return this.http.post<void>(`${API}/projects/${id}/archive`, {});
  }

  access(id: string): Observable<AccessGrant[]> {
    return this.http.get<AccessGrant[]>(`${API}/projects/${id}/access`);
  }

  addGrant(id: string, body: { principal: string; role: string; via: string }): Observable<AccessGrant> {
    return this.http.post<AccessGrant>(`${API}/projects/${id}/access`, body);
  }

  revokeGrant(id: string, grantId: number): Observable<void> {
    return this.http.delete<void>(`${API}/projects/${id}/access/${grantId}`);
  }

  templates(projectId: string): Observable<ProjectTemplate[]> {
    return this.http.get<ProjectTemplate[]>(`${API}/projects/${projectId}/templates`);
  }

  toggleTemplate(projectId: string, key: string, enabled: boolean): Observable<ProjectTemplate> {
    return this.http.put<ProjectTemplate>(`${API}/projects/${projectId}/templates/${key}`, { enabled });
  }

  updateBinding(
    projectId: string,
    widgetId: number,
    body: { query?: string; refresh_interval?: string; drill_template?: string },
  ): Observable<unknown> {
    return this.http.patch(`${API}/projects/${projectId}/templates/widgets/${widgetId}`, body);
  }

  previewBinding(projectId: string, widgetId: number): Observable<QueryPreview> {
    return this.http.post<QueryPreview>(
      `${API}/projects/${projectId}/templates/widgets/${widgetId}/preview`,
      {},
    );
  }

  /** Reads the sources and drafts a setup. Creates no project, dashboard or binding. */
  discoverProject(hint: string): Observable<OnboardingDraft> {
    return this.http.post<OnboardingDraft>(`${API}/onboarding/discover`, { hint });
  }

  /** The draft counts toward nothing until this call records who accepted it. */
  acceptOnboarding(sessionId: number, body: OnboardingAccept): Observable<OnboardingResult> {
    return this.http.post<OnboardingResult>(`${API}/onboarding/${sessionId}/accept`, body);
  }

  connectors(): Observable<ConnectorSummary[]> {
    return this.http.get<ConnectorSummary[]>(`${API}/connectors`);
  }

  connector(key: string): Observable<ConnectorDetail> {
    return this.http.get<ConnectorDetail>(`${API}/connectors/${key}`);
  }

  updateConnector(
    key: string,
    body: { auth_method?: string; config?: Record<string, string> },
  ): Observable<ConnectorDetail> {
    return this.http.put<ConnectorDetail>(`${API}/connectors/${key}`, body);
  }

  /** Write-only. The value goes to the vault; nothing reads it back. */
  rotateSecret(key: string, fieldKey: string, value: string): Observable<void> {
    return this.http.post<void>(`${API}/connectors/${key}/secrets`, { field_key: fieldKey, value });
  }

  testConnector(key: string): Observable<ConnectorTestResult> {
    return this.http.post<ConnectorTestResult>(`${API}/connectors/${key}/test`, {});
  }

  toggleConnector(key: string): Observable<ConnectorSummary> {
    return this.http.post<ConnectorSummary>(`${API}/connectors/${key}/toggle`, {});
  }

  teamInsights(projectId: string, selection: PeriodSelection): Observable<TeamInsights> {
    let params = new HttpParams()
      .set('granularity', selection.granularity)
      .set('preset', selection.preset);
    if (selection.period) params = params.set('period', selection.period);
    if (selection.baseline) params = params.set('baseline', selection.baseline);
    return this.http.get<TeamInsights>(`${API}/projects/${projectId}/team-insights`, { params });
  }

  periodOptions(projectId: string): Observable<FilterOptions> {
    return this.http.get<FilterOptions>(`${API}/projects/${projectId}/periods`);
  }

  featureReadiness(projectId: string, release?: string): Observable<FeatureReadiness> {
    const params = release ? new HttpParams().set('release', release) : undefined;
    return this.http.get<FeatureReadiness>(`${API}/projects/${projectId}/feature-readiness`, { params });
  }

  /** Acknowledgement records a named person and a time. It never closes the signal. */
  acknowledgeAction(projectId: string, actionId: number): Observable<ActionRecord> {
    return this.http.post<ActionRecord>(
      `${API}/projects/${projectId}/actions/${actionId}/acknowledge`,
      {},
    );
  }

  /** AI output counts toward nothing until this call records who accepted it. */
  acceptAiDraft(projectId: string, featureKey: string): Observable<FeatureReadiness> {
    return this.http.post<FeatureReadiness>(
      `${API}/projects/${projectId}/features/${encodeURIComponent(featureKey)}/ai-draft/accept`,
      {},
    );
  }

  rollout(projectId: string): Observable<RolloutBoard> {
    return this.http.get<RolloutBoard>(`${API}/projects/${projectId}/rollout`);
  }

  /** The team agrees the warnings' reasons are fair. Recorded against the caller. */
  recordRolloutSignoff(projectId: string): Observable<RolloutBoard> {
    return this.http.post<RolloutBoard>(`${API}/projects/${projectId}/rollout/signoff`, {});
  }

  /** Refused with the unmet criteria unless every one is met. Admin only, decided server-side. */
  advanceRollout(projectId: string, note: string): Observable<RolloutBoard> {
    return this.http.post<RolloutBoard>(`${API}/projects/${projectId}/rollout/advance`, { note });
  }

  /** Always allowed for an admin, never without a reason. */
  rollbackRollout(projectId: string, note: string): Observable<RolloutBoard> {
    return this.http.post<RolloutBoard>(`${API}/projects/${projectId}/rollout/rollback`, { note });
  }

  // --- Feature Kickoff ------------------------------------------------------------------------

  /**
   * Service-wide kickoff defaults. Readable by anyone (no credential is stored in them);
   * `editable` says whether this person may write them back.
   */
  kickoffSettings(): Observable<KickoffSettings> {
    return this.http.get<KickoffSettings>(`${API}/kickoff/settings`);
  }

  saveKickoffSettings(body: KickoffSettingsWrite): Observable<KickoffSettings> {
    return this.http.put<KickoffSettings>(`${API}/kickoff/settings`, body);
  }

  /** Where each step reads and writes, from configuration. Never carries a credential. */
  kickoffStatus(projectId: string): Observable<KickoffStatus> {
    return this.http.get<KickoffStatus>(`${API}/projects/${projectId}/kickoff/status`);
  }

  kickoffCatalog(projectId: string): Observable<KickoffCatalog> {
    return this.http.get<KickoffCatalog>(`${API}/projects/${projectId}/kickoff/catalog`);
  }

  kickoffAnalyses(projectId: string): Observable<KickoffAnalysisSummary[]> {
    return this.http.get<KickoffAnalysisSummary[]>(`${API}/projects/${projectId}/kickoff/analyses`);
  }

  /** Step 1: reads the PRD and saves a new analysis. Writes nothing outside ShiftLeft. */
  createKickoffAnalysis(projectId: string, prdUrl: string): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${API}/projects/${projectId}/kickoff/analyses`, { prd_url: prdUrl });
  }

  kickoffAnalysis(projectId: string, id: number): Observable<KickoffAnalysis> {
    return this.http.get<KickoffAnalysis>(this.analysisUrl(projectId, id));
  }

  renameKickoffAnalysis(projectId: string, id: number, title: string): Observable<KickoffAnalysis> {
    return this.http.patch<KickoffAnalysis>(this.analysisUrl(projectId, id), { title });
  }

  deleteKickoffAnalysis(projectId: string, id: number): Observable<void> {
    return this.http.delete<void>(this.analysisUrl(projectId, id));
  }

  readKickoffPrd(projectId: string, id: number, prdUrl: string): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/prd`, { prd_url: prdUrl });
  }

  /** Steps 2 and 3. Repos already read are kept unless `refresh`. */
  setKickoffRepos(
    projectId: string,
    id: number,
    role: 'repos' | 'dependencies',
    urls: string[],
    refresh = false,
  ): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/${role}`, { urls, refresh });
  }

  suggestKickoffCompliance(projectId: string, id: number): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/compliance/suggest`, {});
  }

  /** Recorded against the person approving. Required before the analysis can run. */
  approveKickoffCompliance(
    projectId: string,
    id: number,
    selected: string[],
    custom: CustomCompliance[],
  ): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/compliance`, { selected, custom });
  }

  setKickoffDocs(projectId: string, id: number, urls: string[], refresh = false): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/api-docs`, { urls, refresh });
  }

  setKickoffProviders(
    projectId: string,
    id: number,
    providers: { key: string; name: string; docs_url: string }[],
    refresh = false,
  ): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/third-parties`, {
      providers,
      refresh,
    });
  }

  /** Step 7: drafts the plan. Replaces the previous draft and its edits. */
  /**
   * Step 7: read the sample or the design itself, and offer its sections. Writes nothing —
   * the sections offered are the ones the page actually has, plus the standard ones it lacks.
   */
  readKickoffTddPage(
    projectId: string,
    id: number,
    mode: 'sample' | 'existing',
    url: string,
  ): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/tdd/page`, { mode, url });
  }

  /** Confirms which sections the run will write, and where. This confirmation is the acceptance. */
  setKickoffTdd(
    projectId: string,
    id: number,
    body: {
      enabled: boolean;
      selected: string[];
      space_key: string;
      parent_url: string;
      title: string;
    },
  ): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/tdd`, body);
  }

  /** Writes the drafted design again, after a write that didn't land. */
  publishKickoffTdd(projectId: string, id: number): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/tdd/publish`, {});
  }

  /** Drafts the plan. The draft it replaces is kept as a run, so nothing is lost by running again. */
  runKickoffAnalysis(
    projectId: string,
    id: number,
    provider: string,
    model: string,
    instructions: string,
  ): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/run`, {
      provider,
      model,
      instructions,
    });
  }

  /** Amends the plan that is already there. Tasks it leaves alone keep their wording and refs. */
  refineKickoffPlan(
    projectId: string,
    id: number,
    provider: string,
    model: string,
    instructions: string,
  ): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/refine`, {
      provider,
      model,
      instructions,
    });
  }

  /** What the target project offers for each ticket option. Read-only: nothing is written. */
  kickoffBacklogFields(projectId: string, id: number, backlogUrl: string): Observable<BacklogFields> {
    return this.http.get<BacklogFields>(`${this.analysisUrl(projectId, id)}/backlog-fields`, {
      params: { backlog_url: backlogUrl },
    });
  }

  setKickoffBacklogOptions(
    projectId: string,
    id: number,
    options: JiraTicketDefaults,
  ): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/backlog-options`, options);
  }

  kickoffRuns(projectId: string, id: number): Observable<KickoffRunSummary[]> {
    return this.http.get<KickoffRunSummary[]>(`${this.analysisUrl(projectId, id)}/runs`);
  }

  /** One earlier draft, with what changed since the draft before it. */
  kickoffRun(projectId: string, id: number, number: number): Observable<KickoffRunDetail> {
    return this.http.get<KickoffRunDetail>(`${this.analysisUrl(projectId, id)}/runs/${number}`);
  }

  editKickoffPlan(
    projectId: string,
    id: number,
    epicTitle: string,
    tasks: KickoffTaskInput[],
  ): Observable<KickoffAnalysis> {
    return this.http.put<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/plan`, {
      epic_title: epicTitle,
      tasks,
    });
  }

  /** The only external write: the epic and tasks in Jira, recorded against whoever presses it. */
  createKickoffBacklog(projectId: string, id: number, backlogUrl: string): Observable<KickoffAnalysis> {
    return this.http.post<KickoffAnalysis>(`${this.analysisUrl(projectId, id)}/backlog`, {
      backlog_url: backlogUrl,
    });
  }

  private analysisUrl(projectId: string, id: number): string {
    return `${API}/projects/${projectId}/kickoff/analyses/${id}`;
  }

  guide(perspective: string): Observable<PerspectiveGuide> {
    return this.http.get<PerspectiveGuide>(`${API}/guides/${perspective}`);
  }

  accessModel(): Observable<AccessModelEntry[]> {
    return this.http.get<AccessModelEntry[]>(`${API}/access-model`);
  }

  me(): Observable<WhoAmI> {
    return this.http.get<WhoAmI>(`${API}/access-model/me`);
  }
}
