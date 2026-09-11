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
  Kickoff,
  KickoffChoice,
  KickoffConnections,
  KickoffSummary,
  ModelOptions,
  PeriodSelection,
  PrdList,
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

  /** PRD pages the kickoff can start from. The project's own space is listed first. */
  kickoffPrds(projectId: string, query = ''): Observable<PrdList> {
    const params = query ? new HttpParams().set('q', query) : undefined;
    return this.http.get<PrdList>(`${API}/projects/${projectId}/kickoff/prds`, { params });
  }

  /** Where reads and writes go, from configuration. Never carries a credential. */
  kickoffConnections(projectId: string): Observable<KickoffConnections> {
    return this.http.get<KickoffConnections>(`${API}/projects/${projectId}/kickoff/connections`);
  }

  /** Fetched from each provider on request, never a hardcoded list. */
  kickoffModels(projectId: string): Observable<ModelOptions> {
    return this.http.get<ModelOptions>(`${API}/projects/${projectId}/kickoff/models`);
  }

  myKickoffs(projectId: string): Observable<KickoffSummary[]> {
    return this.http.get<KickoffSummary[]>(`${API}/projects/${projectId}/kickoff`);
  }

  /** Reads the PRD and extracts its facts. Writes nothing but the session. */
  startKickoff(projectId: string, body: { page_id: string; provider: string; model: string }): Observable<Kickoff> {
    return this.http.post<Kickoff>(`${API}/projects/${projectId}/kickoff`, body);
  }

  kickoff(projectId: string, id: number): Observable<Kickoff> {
    return this.http.get<Kickoff>(`${API}/projects/${projectId}/kickoff/${id}`);
  }

  /** A person correcting what was read. Every rule re-resolves from the corrected facts. */
  updateKickoffFacts(projectId: string, id: number, facts: { key: string; values: string[] }[]): Observable<Kickoff> {
    return this.http.put<Kickoff>(`${API}/projects/${projectId}/kickoff/${id}/facts`, { facts });
  }

  /** Leaving a recommended action out is refused without a reason. Runs the selected checks. */
  chooseKickoffActions(projectId: string, id: number, choices: KickoffChoice[]): Observable<Kickoff> {
    return this.http.put<Kickoff>(`${API}/projects/${projectId}/kickoff/${id}/actions`, { choices });
  }

  updateKickoffPlan(
    projectId: string,
    id: number,
    body: { decisions?: Record<string, string>; excluded?: string[] },
  ): Observable<Kickoff> {
    return this.http.put<Kickoff>(`${API}/projects/${projectId}/kickoff/${id}/plan`, body);
  }

  /** The confirmation, then the writes (or a dry run). Also retries a plan that partly failed. */
  applyKickoff(projectId: string, id: number): Observable<Kickoff> {
    return this.http.post<Kickoff>(`${API}/projects/${projectId}/kickoff/${id}/apply`, {});
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
