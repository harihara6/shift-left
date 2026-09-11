from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import DrillDown, Freshness, RagState, WidgetGuide
from app.schemas.insights import ChartSpec, EvidenceLink, Tile


class CriterionOut(BaseModel):
    """One exit criterion. `met` is None when the data to judge it is absent - never assumed met."""

    label: str
    met: bool | None
    status: RagState
    evidence: str


class StageOut(BaseModel):
    index: int
    key: str
    label: str
    behaviour: str
    state: str  # "done" | "current" | "ahead"
    criteria: list[CriterionOut] = Field(default_factory=list)


class SurfaceRow(BaseModel):
    key: str
    name: str
    system: str
    gating: bool
    mode: str
    mode_label: str
    coverage: str
    last_event: str
    events: str
    status: RagState
    drill: DrillDown | None = None


class DetectorRow(BaseModel):
    """Detected state against the manual audit, for one artifact."""

    key: str
    name: str
    source: str
    method: str
    audited: int
    correct: int
    false_missing: int
    false_present: int
    accuracy: float
    note: str = ""
    status: RagState
    status_only: bool = False
    drill: DrillDown | None = None


class Signoff(BaseModel):
    by: str | None = None
    at: datetime | None = None


class RolloutBoard(BaseModel):
    project_id: str
    project_label: str
    subtitle: str
    stage: int
    stage_label: str
    stage_since: date
    policy_version: str
    policy_drill: DrillDown | None = None
    audit_note: str
    freshness: Freshness
    evidence_link: EvidenceLink
    tiles: list[Tile] = Field(default_factory=list)
    stages: list[StageOut] = Field(default_factory=list)
    # Whether an admin may advance now, and if not, the unmet criteria - as a list, not a flag.
    can_advance: bool
    advance_blockers: list[str] = Field(default_factory=list)
    signoff: Signoff
    surfaces: list[SurfaceRow] = Field(default_factory=list)
    detectors: list[DetectorRow] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    guide: list[WidgetGuide] = Field(default_factory=list)


class StageChange(BaseModel):
    """A rollback always says why. An advance may, and the audit log keeps it either way."""

    note: str = Field(default="", max_length=2000)
