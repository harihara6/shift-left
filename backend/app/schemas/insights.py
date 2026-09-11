from pydantic import BaseModel, Field

from app.schemas.common import DrillDown, Freshness, RagState, WidgetGuide


class PeriodOut(BaseModel):
    key: str
    label: str
    granularity: str
    start: str
    end: str
    weeks: float
    complete: bool
    window_label: str
    """True when the store holds facts for this period - the filter marks the ones that do not."""
    has_data: bool = True


class PeriodOption(PeriodOut):
    pass


class ComparisonOut(BaseModel):
    """What the page is actually comparing, and what is honest to say about it."""

    current: PeriodOut
    baseline: PeriodOut
    granularity: str
    preset: str
    comparable_lengths: bool
    caveat: str
    """Quarters that make up an aggregated window, and any the store had nothing for."""
    covered_periods: list[str] = Field(default_factory=list)
    missing_periods: list[str] = Field(default_factory=list)
    aggregated: bool = False


class FilterOptions(BaseModel):
    """Everything the period filter needs to render itself without guessing."""

    granularities: list[dict[str, str]]
    presets: list[dict[str, str]]
    periods: dict[str, list[PeriodOption]]
    data_through: str


class GlanceRow(BaseModel):
    row: str
    current: str
    baseline: str
    status: RagState
    drill: DrillDown | None = None


class Tile(BaseModel):
    label: str
    value: str
    note: str = ""
    status: RagState | None = None
    drill: DrillDown | None = None


class Series(BaseModel):
    name: str
    color: str
    data: list[float]


class ChartSpec(BaseModel):
    """One chart component, two modes. Geometry is computed client-side from this spec."""

    key: str
    title: str
    kind: str  # "bar" | "line"
    x_labels: list[str]
    series: list[Series]
    # Every chart names its source and both axes.
    caption: str


class DeckSection(BaseModel):
    key: str
    title: str
    scope: str
    tiles: list[Tile]
    charts: list[ChartSpec]


class EvidenceLink(BaseModel):
    """The structural cross-link from a flow view into the evidence record (PRD s7)."""

    label: str
    perspective: str = "discipline"
    project_id: str
    note: str


class TeamInsights(BaseModel):
    project_id: str
    project_label: str
    comparison: ComparisonOut
    window: str
    comparison_caveat: str
    freshness: Freshness
    evidence_link: EvidenceLink
    glance: list[GlanceRow]
    glance_note: str
    sections: list[DeckSection] = Field(default_factory=list)
    guide: list[WidgetGuide] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
