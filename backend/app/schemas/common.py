from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Rag = Literal["good", "watch", "poor", "neutral", "missing"]

RAG_LABEL: dict[str, str] = {
    "good": "On track",
    "watch": "Watch",
    "poor": "Needs attention",
    "neutral": "Scoped out",
    "missing": "Missing",
}

# Colour is never the only carrier of a RAG state - a glyph ships with it (WCAG 2.2 AA).
RAG_GLYPH: dict[str, str] = {
    "good": "check",
    "watch": "alert",
    "poor": "cross",
    "neutral": "dash",
    "missing": "question",
}


class RagState(BaseModel):
    """A RAG state always travels with its label, its glyph and the reasons behind it.

    `reasons` is a first-class field, never derived at render time - that is what keeps
    a status from becoming a score.
    """

    rag: Rag
    label: str = ""
    glyph: str = ""
    reasons: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, rag: Rag, reasons: list[str] | None = None) -> "RagState":
        return cls(rag=rag, label=RAG_LABEL[rag], glyph=RAG_GLYPH[rag], reasons=reasons or [])


class ConnectorFreshness(BaseModel):
    key: str
    name: str
    state: str
    last_successful_sync: datetime | None = None
    age_minutes: int | None = None
    threshold_minutes: int
    stale: bool
    # Absent data is a gap, never a pass.
    missing: bool = False


class Freshness(BaseModel):
    """Rendered on every widget. A stale source can never contribute to a green state."""

    stale: bool = False
    oldest_sync: datetime | None = None
    note: str = ""
    connectors: list[ConnectorFreshness] = Field(default_factory=list)


class DrillDown(BaseModel):
    """A widget without a drill-down link is a claim, not a signal."""

    label: str
    url: str
    system: str


class WidgetGuide(BaseModel):
    """The four fixed questions every widget must answer before it can ship."""

    widget: str
    decision: str
    source: str
    fetch: str
    tagging: str


class GuideEntry(WidgetGuide):
    widget_key: str


class PerspectiveGuide(BaseModel):
    """Page-level framing plus the four fixed fields per widget."""

    perspective: str
    title: str
    subtitle: str
    audience: list[str] = Field(default_factory=list)
    widgets: list[GuideEntry] = Field(default_factory=list)
    footnote: str = ""
