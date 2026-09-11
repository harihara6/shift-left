"""Guide coverage check.

The four fixed guide questions are stored beside the widget definition, and this check runs at
startup: if a rendered widget has no guide row, the service refuses to come up. That constraint is
the point - it is what stops a widget shipping without saying where its number came from.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guide import PerspectiveGuide, WidgetGuide
from app.schemas.common import GuideEntry
from app.schemas.common import PerspectiveGuide as PerspectiveGuideOut
from app.schemas.common import WidgetGuide as WidgetGuideOut

FOOTNOTE = (
    "A missing connector or an untagged source record renders as a gap, never as a pass. "
    "If something you expect is absent, check the tagging conventions before assuming "
    "the metric is green."
)

# Every widget the UI renders, per perspective. Adding a widget here without a guide row fails boot.
RENDERED_WIDGETS: dict[str, list[str]] = {
    "discipline": ["completeness", "cleared", "readiness_table", "status_reason", "waivers", "actions"],
    "delivery": ["glance", "epics", "stories", "maint", "prs"],
    "settings": ["projects", "widget_bindings", "connectors", "access"],
    "rollout": ["gating_path", "rollout_tiles", "surfaces", "detectors", "rollout_charts"],
    "kickoff": ["prd_source", "facts", "actions", "checks", "plan", "confirm"],
}


class MissingGuideError(RuntimeError):
    pass


async def verify(session: AsyncSession) -> None:
    rows = (await session.execute(select(WidgetGuide.perspective, WidgetGuide.widget_key))).all()
    have = {(p, k) for p, k in rows}
    missing = [
        f"{perspective}.{widget}"
        for perspective, widgets in RENDERED_WIDGETS.items()
        for widget in widgets
        if (perspective, widget) not in have
    ]
    if missing:
        raise MissingGuideError(
            "Widgets rendered without a guide entry (decision / source / fetch / tagging): "
            + ", ".join(missing)
        )


async def _rows(session: AsyncSession, perspective: str) -> list[WidgetGuide]:
    return list(
        (
            await session.execute(
                select(WidgetGuide).where(WidgetGuide.perspective == perspective)
                .order_by(WidgetGuide.position)
            )
        ).scalars().all()
    )


async def for_perspective(session: AsyncSession, perspective: str) -> list[WidgetGuideOut]:
    """The per-widget guide entries a page payload carries alongside its widgets."""
    return [
        WidgetGuideOut(widget=g.widget, decision=g.decision, source=g.source, fetch=g.fetch,
                       tagging=g.tagging)
        for g in await _rows(session, perspective)
    ]


async def page(session: AsyncSession, perspective: str) -> PerspectiveGuideOut | None:
    """The guide modal: page-level framing plus the four fixed fields per widget."""
    framing = await session.get(PerspectiveGuide, perspective)
    if framing is None:
        return None
    return PerspectiveGuideOut(
        perspective=perspective,
        title=framing.title,
        subtitle=framing.subtitle,
        audience=json.loads(framing.audience),
        widgets=[
            GuideEntry(widget_key=g.widget_key, widget=g.widget, decision=g.decision,
                       source=g.source, fetch=g.fetch, tagging=g.tagging)
            for g in await _rows(session, perspective)
        ],
        footnote=FOOTNOTE,
    )
