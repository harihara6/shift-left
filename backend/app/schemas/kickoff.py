from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AnalysisStatus = Literal["draft", "analysed", "created", "partial"]
StepKey = Literal["prd", "repos", "dependencies", "compliance", "api_docs", "third_parties", "plan"]


class Quote(BaseModel):
    line: int
    text: str
    section: str = ""


# --- Where it reads and writes -------------------------------------------------------------------------


class ConnectionOut(BaseModel):
    key: str
    name: str
    # ready: a credential is configured (nothing was called to check it). fallback: works, with less.
    state: Literal["ready", "fallback", "not_configured"]
    via: str
    note: str


class ModelOption(BaseModel):
    id: str
    display_name: str


class ModelProvider(BaseModel):
    key: str
    name: str
    available: bool
    note: str
    models: list[ModelOption] = Field(default_factory=list)
    default_model: str = ""


class KickoffStatus(BaseModel):
    connections: list[ConnectionOut]
    providers: list[ModelProvider]
    default_provider: str


class FrameworkOut(BaseModel):
    key: str
    name: str
    region: str
    category: str
    summary: str
    source: str
    obligations: list[str]


class ProviderCatalogOut(BaseModel):
    key: str
    name: str
    region: str
    category: str
    summary: str
    website: str
    docs_url: str


class CatalogOut(BaseModel):
    frameworks: list[FrameworkOut]
    providers: list[ProviderCatalogOut]


# --- The steps' inputs, as read -------------------------------------------------------------------------


class PrdOut(BaseModel):
    url: str
    page_id: str
    title: str
    space: str
    version: int
    updated: str
    via: Literal["rest", "mcp"]
    via_label: str
    word_count: int
    sections: list[str]
    lines: list[str]
    read_at: datetime
    read_by: str


class LanguageShare(BaseModel):
    name: str
    share: float


class SpecOut(BaseModel):
    path: str
    url: str
    ok: bool
    error: str = ""
    title: str = ""
    version: str = ""
    operation_count: int = 0
    operations: list[str] = Field(default_factory=list)
    deprecated: list[str] = Field(default_factory=list)


class RepoOut(BaseModel):
    # As typed in the step; `html_url` is the repo's own address on GitHub.
    url: str
    html_url: str = ""
    full_name: str
    ok: bool
    error: str = ""
    description: str = ""
    default_branch: str = ""
    ref: str = ""
    commit: str = ""
    commit_url: str = ""
    language: str = ""
    languages: list[LanguageShare] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    visibility: str = ""
    archived: bool = False
    readme_excerpt: str = ""
    file_count: int = 0
    tree_truncated: bool = False
    top_level: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    specs: list[SpecOut] = Field(default_factory=list)
    read_with: str = ""
    read_at: datetime | None = None


class RepoGroupOut(BaseModel):
    repos: list[RepoOut]
    saved: bool
    saved_by: str | None = None


class DocOut(BaseModel):
    url: str
    final_url: str = ""
    ok: bool
    error: str = ""
    kind: str = ""
    title: str = ""
    version: str = ""
    summary: str = ""
    operation_count: int = 0
    operations: list[str] = Field(default_factory=list)
    read_at: datetime | None = None


class DocGroupOut(BaseModel):
    docs: list[DocOut]
    saved: bool
    saved_by: str | None = None


class SuggestionOut(BaseModel):
    # Empty for an obligation outside the catalog (added as a custom item if approved).
    key: str
    name: str
    confidence: Literal["strong", "possible"]
    why: str
    quotes: list[Quote]
    by: Literal["claude", "cursor", "rules"]


class CustomCompliance(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    note: str = Field(default="", max_length=500)


class ComplianceOut(BaseModel):
    suggestions: list[SuggestionOut]
    suggested_by: str | None = None
    suggested_note: str = ""
    suggested_at: datetime | None = None
    # The PRD changed since the suggestions were made.
    suggestions_stale: bool = False
    selected: list[str]
    custom: list[CustomCompliance]
    approved_by: str | None = None
    approved_at: datetime | None = None


class ProviderOut(BaseModel):
    key: str
    name: str
    docs_url: str
    doc: DocOut | None = None
    mentioned: list[Quote] = Field(default_factory=list)


class ProvidersOut(BaseModel):
    providers: list[ProviderOut]
    # Catalog providers the PRD names, offered first: key -> the lines naming them.
    mentioned: dict[str, list[Quote]]
    saved: bool
    saved_by: str | None = None


# --- The plan and the backlog --------------------------------------------------------------------------

TaskType = Literal["Story", "Task", "Spike"]
Estimate = Literal["XS", "S", "M", "L", "XL"]


class Change(BaseModel):
    area: str
    what: str
    why: str


class RepoWorkOut(BaseModel):
    repo: str
    summary: str
    changes: list[Change]


class DependencyNeedOut(BaseModel):
    repo: str
    relies_on: str
    status: Literal["available", "missing", "unclear"]
    evidence: str
    action: str


class TaskOut(BaseModel):
    ref: str
    title: str
    type: TaskType
    repo: str
    description: str
    acceptance_criteria: list[str]
    depends_on: list[str]
    estimate: Estimate
    compliance: list[str]
    quotes: list[Quote]
    origin: Literal["claude", "cursor", "rules", "person"]
    edited_by: str | None = None


class PlanOut(BaseModel):
    summary: str
    epic_title: str
    epic_description: str
    repo_work: list[RepoWorkOut]
    dependency_needs: list[DependencyNeedOut]
    risks: list[str]
    open_questions: list[str]
    tasks: list[TaskOut]
    notes: list[str]
    reader: Literal["claude", "cursor", "rules"]
    model: str
    drafted_by: str
    note: str
    run_by: str
    run_at: datetime
    run_number: int
    edited_by: str | None = None
    edited_at: datetime | None = None
    # Inputs changed since this plan was drafted: which ones. Run again to draft from them.
    stale: list[str] = Field(default_factory=list)


class TicketOut(BaseModel):
    ref: str
    title: str
    status: Literal["created", "exists", "failed"]
    key: str = ""
    url: str = ""
    message: str = ""


class BacklogOut(BaseModel):
    url: str
    site: str
    project_key: str
    board_id: str = ""
    label: str
    created_by: str
    created_at: datetime
    epic: TicketOut
    tickets: list[TicketOut]
    note: str = ""
    failed: int
    attempts: int


class BacklogTargetOut(BaseModel):
    url: str
    project_key: str
    board_id: str = ""


class StepOut(BaseModel):
    key: StepKey
    label: str
    done: bool
    summary: str


class AnalysisOut(BaseModel):
    id: int
    project_id: str
    title: str
    status: AnalysisStatus
    created_by: str
    created_at: datetime | None
    updated_by: str
    updated_at: datetime | None
    steps: list[StepOut]
    # What still stands between this analysis and a run, as a list (never a score).
    run_blockers: list[str]
    prd: PrdOut | None
    repos: RepoGroupOut
    dependencies: RepoGroupOut
    compliance: ComplianceOut
    api_docs: DocGroupOut
    third_parties: ProvidersOut
    plan: PlanOut | None
    backlog_target: BacklogTargetOut | None
    backlog: BacklogOut | None


class AnalysisSummary(BaseModel):
    id: int
    title: str
    status: AnalysisStatus
    created_by: str
    created_at: datetime | None
    updated_by: str
    updated_at: datetime | None
    steps_done: int
    steps_total: int
    repo_count: int
    task_count: int
    drafted_by: str | None
    backlog_key: str | None
    stale: bool


# --- Requests ------------------------------------------------------------------------------------------


class PrdRequest(BaseModel):
    prd_url: str = Field(min_length=1, max_length=2000)


class TitleUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class UrlsUpdate(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=20)
    # Read every URL again, not only the ones not read yet.
    refresh: bool = False


class ComplianceApproval(BaseModel):
    selected: list[str] = Field(default_factory=list, max_length=40)
    custom: list[CustomCompliance] = Field(default_factory=list, max_length=20)


class ProviderIn(BaseModel):
    # A catalog provider's key, or empty for one named by hand.
    key: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=120)
    docs_url: str = Field(default="", max_length=2000)


class ProvidersUpdate(BaseModel):
    providers: list[ProviderIn] = Field(default_factory=list, max_length=20)
    refresh: bool = False


class RunRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)


class TaskIn(BaseModel):
    ref: str = Field(default="", max_length=12)
    title: str = Field(min_length=1, max_length=250)
    type: TaskType
    repo: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=8000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    estimate: Estimate = "M"
    compliance: list[str] = Field(default_factory=list, max_length=20)


class PlanEdit(BaseModel):
    epic_title: str = Field(min_length=1, max_length=250)
    tasks: list[TaskIn] = Field(max_length=150)


class BacklogRequest(BaseModel):
    backlog_url: str = Field(min_length=1, max_length=2000)
