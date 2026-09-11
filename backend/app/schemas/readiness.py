from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import DrillDown, Freshness, RagState, WidgetGuide
from app.schemas.insights import Tile


class ArtifactRow(BaseModel):
    """One row of the eleven-row evidence checklist."""

    key: str
    name: str
    accountable: str
    gate: str
    source: str
    status: RagState
    status_label: str
    note: str = ""
    counts_toward_gate: bool
    drill: DrillDown | None = None
    # Threat models, security findings and pen-test evidence: presence and status only.
    status_only: bool = False


class Completeness(BaseModel):
    """Present-and-fresh over required, with waived artifacts out of the denominator."""

    done: int
    total: int
    percent: int
    label: str
    status: RagState


class AiDraft(BaseModel):
    """Assistive until a named person accepts it. Until then it counts toward nothing."""

    text: str
    drawn_from: str
    accepted_by: str | None = None
    accepted_at: datetime | None = None
    accepted: bool = False
    note: str


class FeatureRow(BaseModel):
    key: str
    name: str
    tier: str
    gate: str
    owner: str
    next_action: str
    action_age: str
    status: RagState
    reason: str
    ready: Completeness
    done: Completeness
    missing: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRow] = Field(default_factory=list)
    ai: AiDraft | None = None
    drill: DrillDown | None = None
    gate_note: str


class Waiver(BaseModel):
    artifact: str
    feature_key: str
    tier: str
    owner: str
    waived_at: str
    rationale: str
    # A rationale on the deny-list is surfaced as a planning signal, not quietly accepted.
    flagged: bool = False
    flag_note: str = ""


class Action(BaseModel):
    id: int
    signal: str
    next_action: str
    owner: str
    age: str
    status: str
    status_label: str
    severity: RagState
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None


class FlowLink(BaseModel):
    """The other half of the cross-link: evidence -> the flow record for the same team."""

    label: str
    perspective: str = "delivery"
    project_id: str
    note: str


class FeatureReadiness(BaseModel):
    project_id: str
    project_label: str
    release: str
    evidence_of_record: bool = True
    subtitle: str
    freshness: Freshness
    flow_link: FlowLink
    tiles: list[Tile] = Field(default_factory=list)
    features: list[FeatureRow] = Field(default_factory=list)
    waivers: list[Waiver] = Field(default_factory=list)
    waiver_note: str
    actions: list[Action] = Field(default_factory=list)
    guide: list[WidgetGuide] = Field(default_factory=list)
