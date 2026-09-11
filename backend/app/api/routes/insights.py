from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, require
from app.db.session import get_session
from app.models.project import Project
from app.schemas.common import PerspectiveGuide
from app.schemas.insights import FilterOptions, PeriodOption, TeamInsights
from app.services import calendar_context, guides, periods
from app.services.insights import build, period_out

router = APIRouter(tags=["insights"])


@router.get("/projects/{project_id}/periods", response_model=FilterOptions)
async def period_options(
    project: Project = Depends(require("viewer")), session: AsyncSession = Depends(get_session)
) -> FilterOptions:
    """Everything the period filter needs: granularities, presets, and the selectable periods.

    Periods the store holds nothing for are still listed, flagged `has_data: false`, so choosing
    one is a deliberate act rather than a surprise empty page.
    """
    today = calendar_context.today()
    through = await calendar_context.data_through(session, project.id)
    stored = await calendar_context.stored_period_keys(session, project.id)

    options: dict[str, list[PeriodOption]] = {}
    for granularity in periods.GRANULARITIES:
        entries = []
        for period in periods.recent(granularity, today, through):
            quarters = periods.constituent_quarters(period, through)
            has_data = any(q.key in stored for q in quarters)
            entries.append(PeriodOption(**period_out(period, has_data).model_dump()))
        options[granularity] = entries

    return FilterOptions(
        granularities=[
            {"key": key, "label": periods.GRANULARITY_LABEL[key]} for key in periods.GRANULARITIES
        ],
        presets=[{"key": key, "label": label} for key, label in periods.PRESETS.items()],
        periods=options,
        data_through=through.isoformat(),
    )


@router.get("/projects/{project_id}/team-insights", response_model=TeamInsights)
async def team_insights(
    granularity: str = Query("quarter", description="quarter · half · year"),
    preset: str = Query("previous", description="previous · last_year · custom"),
    period: str | None = Query(None, description="Period key to report on, e.g. Q3-2026"),
    baseline: str | None = Query(None, description="Period key to compare against, with preset=custom"),
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> TeamInsights:
    today = calendar_context.today()
    through = await calendar_context.data_through(session, project.id)
    comparison = periods.resolve(granularity, preset, today, through, period, baseline)

    payload = await build(session, project, comparison, through)
    if payload is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No delivery snapshot for {project.name} in {comparison.current.label}. "
            "An absent snapshot is a gap, not an empty dashboard.",
        )
    return payload


@router.get("/guides/{perspective}", response_model=PerspectiveGuide)
async def perspective_guide(
    perspective: str,
    _: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PerspectiveGuide:
    """Page-level framing plus the four fixed fields per widget."""
    guide = await guides.page(session, perspective)
    if guide is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No guide for that perspective")
    return guide
