from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.settings import ProjectDetail


class CandidateOut(BaseModel):
    """One thing a source returned. `url` is what makes it checkable rather than claimed."""

    id: str
    connector_key: str
    slot: str
    ref: str
    title: str
    url: str
    detail: dict[str, str] = Field(default_factory=dict)
    matched_on: list[str] = Field(default_factory=list)


class SourceOut(BaseModel):
    connector_key: str
    connector_name: str
    available: bool
    state: str
    note: str
    candidates: list[CandidateOut] = Field(default_factory=list)


class SlotOut(BaseModel):
    """A resolved slot, with the evidence and the confidence attached to it.

    Confidence never travels alone: it is shown beside the candidate's own source link, so a
    number can always be checked against the thing it is about.
    """

    slot: str
    candidate: CandidateOut | None = None
    confidence: float = 0.0
    rationale: str = ""


class BindingOut(BaseModel):
    template_key: str
    widget_name: str
    connector_key: str
    position: int
    catalog_query: str
    query: str
    filled_slots: list[str] = Field(default_factory=list)
    unresolved_slots: list[str] = Field(default_factory=list)
    leftovers: list[str] = Field(default_factory=list)
    validated: bool = False
    row_count: int = 0
    note: str = ""
    ready: bool = False
    generic: bool = False


class TemplateOut(BaseModel):
    template_key: str
    name: str
    perspective: str
    propose_enabled: bool
    reason: str
    bindings: list[BindingOut] = Field(default_factory=list)


class DiscoverRequest(BaseModel):
    hint: str = Field(min_length=2, max_length=200)


class DraftOut(BaseModel):
    """A proposal. Nothing in it exists until it is accepted."""

    id: int
    hint: str
    status: str
    # "claude" or "name-match" — how the assignment below was arrived at.
    mode: str
    note: str
    discovery_available: bool
    caveats: list[str] = Field(default_factory=list)
    project_name: str
    project_key: str
    owner: str = ""
    sources: list[SourceOut] = Field(default_factory=list)
    slots: list[SlotOut] = Field(default_factory=list)
    templates: list[TemplateOut] = Field(default_factory=list)
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    project_id: str | None = None


class AcceptedBinding(BaseModel):
    template_key: str = Field(max_length=32)
    widget_name: str = Field(max_length=200)
    # The query as the person accepting it has it on screen — edits included. An empty query
    # is a valid acceptance: the widget renders Missing until someone binds it.
    query: str = Field(default="", max_length=4000)


class AcceptRequest(BaseModel):
    """What a named person is actually accepting. Everything is re-stated, nothing implied."""

    key: str = Field(min_length=2, max_length=16, pattern=r"^[A-Z][A-Z0-9]{1,15}$")
    # Same rule as POST /projects: the project id is minted from the name.
    name: str = Field(min_length=1, max_length=160, pattern=r"[A-Za-z0-9]")
    owner: str = Field(min_length=1, max_length=160)
    templates: list[str] = Field(default_factory=list, max_length=20)
    bindings: list[AcceptedBinding] = Field(default_factory=list, max_length=200)


class AcceptResult(BaseModel):
    project: ProjectDetail
    templates_enabled: list[str] = Field(default_factory=list)
    bindings_applied: int = 0
    bindings_left_empty: int = 0
    accepted_by: str
    accepted_at: datetime
    note: str
