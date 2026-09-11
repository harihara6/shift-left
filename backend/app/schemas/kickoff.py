from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import RagState


class Link(BaseModel):
    label: str
    url: str


class Quote(BaseModel):
    text: str
    section: str = ""


class PrdPage(BaseModel):
    page_id: str
    title: str
    space: str
    url: str
    version: int
    updated: str
    author: str
    # The PRD belongs to the project the kickoff runs in. Others are listed, never hidden.
    own_project: bool = False


class PrdList(BaseModel):
    pages: list[PrdPage]
    note: str
    # False when the live source can't be read; `note` says why. Never an empty list posing as none.
    available: bool = True


class Connection(BaseModel):
    key: str
    name: str
    direction: Literal["read", "write"]
    # "configured" is from configuration alone: nothing is called to check it.
    state: Literal["example", "configured", "not_configured", "not_built", "dry_run"]
    note: str


class Connections(BaseModel):
    sources: Literal["fixtures", "live"]
    write_mode: Literal["dry-run", "live"]
    connections: list[Connection]


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


class ModelOptions(BaseModel):
    providers: list[ModelProvider]
    default_provider: str


class StartRequest(BaseModel):
    page_id: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=120)


class AllowedValue(BaseModel):
    value: str
    label: str


class FactOut(BaseModel):
    key: str
    label: str
    values: list[str]
    value_labels: list[str]
    # "stated" (from the PRD, quoted), "not_stated", or "confirmed" (set by a person).
    status: str
    quotes: list[Quote]
    confirmed_by: str | None = None
    # Empty for free-text facts (services, third parties).
    allowed: list[AllowedValue] = Field(default_factory=list)


class TierOut(BaseModel):
    tier: str
    reason: str
    undetermined: bool
    quotes: list[Quote]


class ActionOut(BaseModel):
    key: str
    label: str
    group: str
    group_label: str
    target: str
    description: str
    outcome: Literal["applies", "not_applicable", "undetermined"]
    outcome_label: str
    reason: str
    quotes: list[Quote]
    question: str = ""
    recommended: bool
    selected: bool
    skip_reason: str = ""
    # A reason for leaving a recommended action out that is on the deny-list.
    skip_flagged: bool = False


class DrawnFrom(BaseModel):
    kind: str
    text: str
    url: str = ""
    section: str = ""


class SuggestionOut(BaseModel):
    key: str
    label: str
    why: str
    target: str
    source: str
    kind: str
    decision: Literal["pending", "accepted", "dismissed"]
    drawn_from: list[DrawnFrom]


class FindingOut(BaseModel):
    id: str
    status: Literal["ok", "gap", "blocker", "not_checked"]
    title: str
    detail: str = ""
    link: Link | None = None
    quote: Quote | None = None


class CheckOut(BaseModel):
    key: str
    label: str
    note: str
    findings: list[FindingOut]


class PlanItemOut(BaseModel):
    id: str
    group: str
    kind: str
    title: str
    detail: str
    project: str
    labels: list[str]
    drawn_from: list[DrawnFrom]
    diff: dict[str, Any] | None = None
    included: bool


class CoverageOut(BaseModel):
    artifact: str
    name: str
    gate: str
    state: str
    item_id: str | None
    note: str = ""


class PlanOut(BaseModel):
    items: list[PlanItemOut]
    coverage: list[CoverageOut]
    notes: list[str]
    catalog_version: int
    # The product index isn't in Confluence, so its version is whatever it states, or a content hash.
    index_version: str


class ResultOut(BaseModel):
    item_id: str
    group: str
    title: str
    # created / updated / exists: done, with a link. handoff: a person finishes it, and the message
    # says how. failed: nothing was written for it, and a retry will try again.
    status: Literal["dry_run", "skipped", "created", "updated", "exists", "handoff", "failed"]
    message: str
    link: Link | None = None


class KickoffOut(BaseModel):
    id: int
    project_id: str
    status: Literal["context", "planned", "applying", "partial", "applied"]
    page: PrdPage
    provider: str
    model: str
    reader: str
    # "Claude (claude-opus-5)" or "Rule-based reader". Shown beside every drafted item.
    drafted_by: str
    note: str
    source_note: str
    source_mode: Literal["fixtures", "live"] = "fixtures"
    write_mode: Literal["dry-run", "live"]
    facts: list[FactOut]
    tier: TierOut
    actions: list[ActionOut]
    suggestions: list[SuggestionOut]
    checks: list[CheckOut]
    headline: RagState | None = None
    checked_at: datetime | None = None
    plan: PlanOut | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    results: list[ResultOut] = Field(default_factory=list)
    created_at: datetime | None = None


class KickoffSummary(BaseModel):
    id: int
    page_title: str
    status: str
    model: str
    created_at: datetime | None
    approved_by: str | None


class FactEdit(BaseModel):
    key: str
    values: list[str] = Field(default_factory=list, max_length=20)


class FactsUpdate(BaseModel):
    facts: list[FactEdit] = Field(min_length=1)


class Choice(BaseModel):
    key: str
    selected: bool
    skip_reason: str = Field(default="", max_length=500)


class ActionsUpdate(BaseModel):
    choices: list[Choice]


class PlanUpdate(BaseModel):
    decisions: dict[str, Literal["pending", "accepted", "dismissed"]] = Field(default_factory=dict)
    # The full list of plan items to leave out. Omitted means "leave the current list as it is".
    excluded: list[str] | None = None
