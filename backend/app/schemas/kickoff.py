from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AnalysisStatus = Literal["draft", "analysed", "created", "partial"]
StepKey = Literal[
    "prd", "repos", "dependencies", "compliance", "api_docs", "third_parties", "tdd", "plan"
]


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


class MaterialGroupOut(BaseModel):
    """Step 3: what we rely on. Code and documents alike — a service we call, a Confluence page
    describing it, a docs site. Both lists can be empty; the step is still done once saved."""

    repos: list[RepoOut]
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


# --- The technical design ---------------------------------------------------------------------------


class TddSourceOut(BaseModel):
    url: str
    page_id: str
    title: str
    space: str
    version: int
    read_with: str
    read_at: datetime | None = None
    line_count: int = 0


class TddSectionChoice(BaseModel):
    key: str
    name: str
    summary: str = ""
    level: int = 2
    # Whether the page already has this section. A sample also offers the standard ones it lacks.
    present: bool
    chars: int = 0
    recommended: bool = False


class TddOut(BaseModel):
    """Step 7 as it stands: what will be written, where, and who confirmed it."""

    enabled: bool = False
    mode: Literal["sample", "existing"] = "sample"
    source: TddSourceOut | None = None
    sections: list[TddSectionChoice] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    space_key: str = ""
    parent_url: str = ""
    title: str = ""
    approved_by: str | None = None
    approved_at: datetime | None = None


class TddDiagramOut(BaseModel):
    kind: str
    title: str
    source: str


class TddSectionOut(BaseModel):
    key: str
    name: str
    body_markdown: str = ""
    diagrams: list[TddDiagramOut] = Field(default_factory=list)
    # Assembled from the analysis rather than drafted: the traceability matrix.
    built: bool = False
    note: str = ""
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class TddPublishedOut(BaseModel):
    url: str
    page_id: str
    version: int
    space_key: str
    title: str
    written: list[str]
    appended: list[str]
    published_by: str
    published_at: datetime


class TddDocumentOut(BaseModel):
    sections: list[TddSectionOut]
    notes: list[str]
    drafted: bool
    # Why it wasn't drafted, or wasn't written. Empty when it was.
    note: str
    run_number: int
    published: TddPublishedOut | None = None


class TddPageRequest(BaseModel):
    mode: Literal["sample", "existing"]
    url: str = Field(min_length=1, max_length=2000)


class TddUpdate(BaseModel):
    enabled: bool
    selected: list[str] = Field(default_factory=list, max_length=40)
    space_key: str = Field(default="", max_length=64)
    parent_url: str = Field(default="", max_length=2000)
    title: str = Field(default="", max_length=250)


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
    # What the person asked for on top of the prompt, so a reader can see what it was told.
    instructions: str = ""
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


class JiraDefaults(BaseModel):
    """What every ticket this service creates should carry, where a team has a convention for it.

    The two identity labels (`shiftleft-kickoff-<id>` and `shiftleft-tracked`) are always applied
    on top of these: finding the tickets again depends on them.
    """

    labels: list[str] = Field(default_factory=list, max_length=20)
    components: list[str] = Field(default_factory=list, max_length=20)
    priority: str = Field(default="", max_length=60)
    fix_version: str = Field(default="", max_length=120)
    assignee_account_id: str = Field(default="", max_length=128)
    due_in_days: int | None = Field(default=None, ge=0, le=365)
    story_points_field: str = Field(default="", max_length=60)


class TddCatalogSection(BaseModel):
    """A section a technical design is expected to carry. Reference data."""

    key: str
    name: str
    summary: str
    default: bool


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
    dependencies: MaterialGroupOut
    compliance: ComplianceOut
    api_docs: DocGroupOut
    third_parties: ProvidersOut
    tdd: TddOut
    tdd_document: TddDocumentOut | None
    plan: PlanOut | None
    # Prefilled into the next run from the service-wide standing instruction. Editable per run.
    instructions: str = ""
    # What every ticket this analysis creates will carry, on top of the two identity labels.
    backlog_options: JiraDefaults = Field(default_factory=lambda: JiraDefaults())
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
    # Steers what the draft emphasises. It never relaxes what the draft is held to.
    instructions: str = Field(default="", max_length=2000)


class RefineRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=2000)


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


# --- Run history ------------------------------------------------------------------------------------------


class RunSummaryOut(BaseModel):
    run_number: int
    kind: Literal["run", "refine"]
    reader: str
    model: str
    instructions: str
    task_count: int
    created_by: str
    created_at: datetime | None
    # Whether this run's draft is the one on the page now.
    is_current: bool


class RunTaskOut(BaseModel):
    ref: str
    title: str
    repo: str = ""


class RunChangeOut(BaseModel):
    ref: str
    title: str
    field: str
    before: str
    after: str


class RunDiffOut(BaseModel):
    """What changed between two drafts. A list of differences, never a similarity score."""

    added: list[RunTaskOut]
    removed: list[RunTaskOut]
    changed: list[RunChangeOut]
    epic_title_changed: bool
    summary_changed: bool


class RunDetailOut(BaseModel):
    run_number: int
    kind: Literal["run", "refine"]
    instructions: str
    created_by: str
    created_at: datetime | None
    plan: PlanOut
    # Against the run before it, when there was one.
    diff: RunDiffOut | None


# --- Service-wide defaults --------------------------------------------------------------------------------


class BacklogFieldsOut(BaseModel):
    """What the target Jira project offers. A field this account can't read comes back empty, and
    is then simply not offered - never guessed at."""

    project_key: str
    components: list[str]
    fix_versions: list[str]
    priorities: list[str]


class KickoffSettingsOut(BaseModel):
    tdd_template_url: str
    tdd_space_key: str
    tdd_parent_url: str
    tdd_sections: list[str]
    jira_project_url: str
    jira_defaults: JiraDefaults
    analysis_prompt: str
    tdd_prompt: str
    updated_by: str
    updated_at: datetime | None
    # The sections a technical design is expected to carry, to tick defaults from. Reference data.
    section_catalog: list[TddCatalogSection]
    # Whether this caller may change these. The API decides; the page only renders the answer.
    editable: bool


class KickoffSettingsWrite(BaseModel):
    tdd_template_url: str = Field(default="", max_length=2000)
    tdd_space_key: str = Field(default="", max_length=64)
    tdd_parent_url: str = Field(default="", max_length=2000)
    tdd_sections: list[str] = Field(default_factory=list, max_length=40)
    jira_project_url: str = Field(default="", max_length=2000)
    jira_defaults: JiraDefaults = Field(default_factory=JiraDefaults)
    analysis_prompt: str = Field(default="", max_length=2000)
    tdd_prompt: str = Field(default="", max_length=2000)
