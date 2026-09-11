"""Feature Kickoff: seven steps from a PRD to an ordered backlog, saved as an analysis.

Access is the project's (product rule 8): anyone with a role on the project can open its analyses,
and a contributor can change them, run them and create their tasks in Jira. Creating in Jira is
the only external write, and it is recorded against the person who pressed the button.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, require
from app.db.session import get_session
from app.models.kickoff import KickoffAnalysis
from app.models.project import Project
from app.schemas.kickoff import (
    AnalysisOut,
    AnalysisSummary,
    BacklogRequest,
    CatalogOut,
    ComplianceApproval,
    KickoffStatus,
    PlanEdit,
    PrdRequest,
    ProvidersUpdate,
    RunRequest,
    TitleUpdate,
    UrlsUpdate,
)
from app.services import audit
from app.services import kickoff as service

router = APIRouter(prefix="/projects", tags=["kickoff"])
BASE = "/{project_id}/kickoff"
ONE = BASE + "/analyses/{analysis_id}"


def _refused(exc: service.Refused) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"message": exc.message, "blockers": exc.blockers})


async def _analysis(session: AsyncSession, project: Project, analysis_id: int) -> KickoffAnalysis:
    row = await session.get(KickoffAnalysis, analysis_id)
    if row is None or row.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return row


async def _saved(session: AsyncSession, row: KickoffAnalysis) -> AnalysisOut:
    await session.commit()
    await session.refresh(row)
    return service.view(row)


@router.get(BASE + "/status", response_model=KickoffStatus)
async def kickoff_status(
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> KickoffStatus:
    """Where each step reads and writes, from configuration. Never returns a credential."""
    return await service.status(session)


@router.get(BASE + "/catalog", response_model=CatalogOut)
async def kickoff_catalog(project: Project = Depends(require("viewer"))) -> CatalogOut:
    return service.catalog()


@router.get(BASE + "/analyses", response_model=list[AnalysisSummary])
async def list_analyses(
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> list[AnalysisSummary]:
    rows = (
        await session.execute(
            select(KickoffAnalysis)
            .where(KickoffAnalysis.project_id == project.id)
            .order_by(KickoffAnalysis.updated_at.desc(), KickoffAnalysis.id.desc())
            .limit(100)
        )
    ).scalars()
    return [service.summary(r) for r in rows]


@router.post(BASE + "/analyses", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
async def create_analysis(
    body: PrdRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 1: read the PRD. Creates the analysis and nothing else."""
    try:
        row = await service.create(session, project, user.email, body.prd_url)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await session.flush()
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_analysis_create",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={
            "page_id": row.inputs["prd"]["page_id"],
            "version": row.inputs["prd"]["version"],
            "via": row.inputs["prd"]["via"],
        },
        note="Read-only: the PRD was read. Nothing was written outside ShiftLeft.",
    )
    return await _saved(session, row)


@router.get(ONE, response_model=AnalysisOut)
async def get_analysis(
    analysis_id: int,
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    return service.view(await _analysis(session, project, analysis_id))


@router.patch(ONE, response_model=AnalysisOut)
async def rename_analysis(
    analysis_id: int,
    body: TitleUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    row = await _analysis(session, project, analysis_id)
    service.rename(row, user.email, body.title)
    return await _saved(session, row)


@router.delete(ONE, status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(
    analysis_id: int,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Deletes the analysis in ShiftLeft. Anything already created in Jira stays in Jira."""
    row = await _analysis(session, project, analysis_id)
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_analysis_delete",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={"title": row.title, "status": row.status, "backlog": (row.backlog or {}).get("project_key")},
        note="The analysis was deleted. Tickets it created in Jira, if any, were not touched.",
    )
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(ONE + "/prd", response_model=AnalysisOut)
async def set_prd(
    analysis_id: int,
    body: PrdRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 1 again: read the page afresh, or a different page."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.read_prd(session, row, user.email, body.prd_url)
    except service.Refused as exc:
        raise _refused(exc) from exc
    return await _saved(session, row)


async def _repos(
    role: str, analysis_id: int, body: UrlsUpdate, project: Project, user: CurrentUser, session: AsyncSession
) -> AnalysisOut:
    row = await _analysis(session, project, analysis_id)
    try:
        await service.set_repos(session, row, role, body.urls, body.refresh, user.email)
    except service.Refused as exc:
        raise _refused(exc) from exc
    return await _saved(session, row)


@router.put(ONE + "/repos", response_model=AnalysisOut)
async def set_repos(
    analysis_id: int,
    body: UrlsUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 2: the repos the feature is coded in, read from GitHub."""
    return await _repos("repos", analysis_id, body, project, user, session)


@router.put(ONE + "/dependencies", response_model=AnalysisOut)
async def set_dependencies(
    analysis_id: int,
    body: UrlsUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 3: the repos the feature relies on. An empty list is a valid answer."""
    return await _repos("dependencies", analysis_id, body, project, user, session)


@router.post(ONE + "/compliance/suggest", response_model=AnalysisOut)
async def suggest_compliance(
    analysis_id: int,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 4a: propose compliance from the PRD. Proposes only; approving is the next call."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.suggest_compliance(row, user.email)
    except service.Refused as exc:
        raise _refused(exc) from exc
    return await _saved(session, row)


@router.put(ONE + "/compliance", response_model=AnalysisOut)
async def approve_compliance(
    analysis_id: int,
    body: ComplianceApproval,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 4b: the approved selection, recorded against the person approving it."""
    row = await _analysis(session, project, analysis_id)
    try:
        service.approve_compliance(row, user.email, body)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_compliance_approve",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={"selected": body.selected, "custom": [c.name for c in body.custom]},
    )
    return await _saved(session, row)


@router.put(ONE + "/api-docs", response_model=AnalysisOut)
async def set_api_docs(
    analysis_id: int,
    body: UrlsUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 5: our API docs, read from the URLs given."""
    row = await _analysis(session, project, analysis_id)
    await service.set_docs(row, body.urls, body.refresh, user.email)
    return await _saved(session, row)


@router.put(ONE + "/third-parties", response_model=AnalysisOut)
async def set_third_parties(
    analysis_id: int,
    body: ProvidersUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 6: the third-party providers relied on, and their docs."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.set_providers(row, body, user.email)
    except service.Refused as exc:
        raise _refused(exc) from exc
    return await _saved(session, row)


@router.post(ONE + "/run", response_model=AnalysisOut)
async def run_analysis(
    analysis_id: int,
    body: RunRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 7: draft the plan. Replaces the previous draft, including edits made to it."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.run(row, user.email, body.provider, body.model)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_analysis_run",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={
            "run": row.runs,
            "reader": row.plan["reader"],
            "model": row.plan["model"],
            "tasks": len(row.plan["tasks"]),
        },
        note="A draft. It counts toward nothing until a named person creates it in the backlog.",
    )
    return await _saved(session, row)


@router.put(ONE + "/plan", response_model=AnalysisOut)
async def edit_plan(
    analysis_id: int,
    body: PlanEdit,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    row = await _analysis(session, project, analysis_id)
    try:
        service.edit_plan(row, user.email, body)
    except service.Refused as exc:
        raise _refused(exc) from exc
    return await _saved(session, row)


@router.post(ONE + "/backlog", response_model=AnalysisOut)
async def create_backlog(
    analysis_id: int,
    body: BacklogRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Create the epic and tasks in Jira, in order. Also the retry for tasks that failed."""
    row = await _analysis(session, project, analysis_id)
    try:
        result = await service.create_backlog(session, row, user.email, body.backlog_url)
    except service.Refused as exc:
        raise _refused(exc) from exc
    counts: dict[str, int] = {}
    for ticket in [result["epic"], *result["tickets"]]:
        counts[ticket["status"]] = counts.get(ticket["status"], 0) + 1
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_backlog_create",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={
            "project_key": result["project_key"],
            "counts": counts,
            "attempt": result["attempts"],
            "reader": row.plan["reader"],
            "model": row.plan["model"],
        },
        note="The named acceptance of an AI or rule-based draft: its tasks were created in Jira.",
    )
    return await _saved(session, row)
