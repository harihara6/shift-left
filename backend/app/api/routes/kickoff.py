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
    BacklogFieldsOut,
    BacklogRequest,
    CatalogOut,
    ComplianceApproval,
    JiraDefaults,
    KickoffStatus,
    PlanEdit,
    PrdRequest,
    ProvidersUpdate,
    RefineRequest,
    RunDetailOut,
    RunRequest,
    RunSummaryOut,
    TddPageRequest,
    TddUpdate,
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


@router.post(ONE + "/tdd/page", response_model=AnalysisOut)
async def read_tdd_page(
    analysis_id: int,
    body: TddPageRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Step 7: read the sample or the design itself, and offer its sections. Writes nothing."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.read_tdd_page(session, row, user.email, body.mode, body.url)
    except service.Refused as exc:
        raise _refused(exc) from exc
    return await _saved(session, row)


@router.put(ONE + "/tdd", response_model=AnalysisOut)
async def write_tdd(
    analysis_id: int,
    body: TddUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Confirm which sections the run will write, and where.

    This is the acceptance: the run writes these sections and no others, into a page a team owns.
    It is recorded against the person who confirmed it and audited, which is why it is a step of
    its own rather than a checkbox beside the Run button.
    """
    row = await _analysis(session, project, analysis_id)
    try:
        service.set_tdd(row, user.email, body)
    except service.Refused as exc:
        raise _refused(exc) from exc
    t = row.inputs["tdd"]
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_tdd_approve",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={
            "enabled": t["enabled"],
            "mode": t.get("mode", ""),
            "page_id": (t.get("source") or {}).get("page_id", ""),
            "sections": t.get("selected", []),
            "space_key": t.get("space_key", ""),
        },
        note="What the next run will write to Confluence. Nothing is written until it runs.",
    )
    return await _saved(session, row)


@router.post(ONE + "/tdd/publish", response_model=AnalysisOut)
async def publish_tdd(
    analysis_id: int,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Write the drafted design again, after a write that didn't land."""
    row = await _analysis(session, project, analysis_id)
    if not row.tdd or not row.tdd.get("sections"):
        raise _refused(service.Refused("There is no drafted design to publish. Run the analysis first."))
    await service.publish_tdd(session, row, user.email)
    published = (row.tdd or {}).get("published") or {}
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_tdd_publish",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={
            "page_id": published.get("page_id", ""),
            "version": published.get("version", 0),
            "written": published.get("written", []),
            "appended": published.get("appended", []),
            "note": (row.tdd or {}).get("note", ""),
        },
        note="Only the confirmed sections are written; the rest of the page is left as it was.",
    )
    return await _saved(session, row)


@router.post(ONE + "/run", response_model=AnalysisOut)
async def run_analysis(
    analysis_id: int,
    body: RunRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Draft the plan. The draft it replaces is kept as a run, so nothing is lost by running again."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.run(session, row, user.email, body.provider, body.model, body.instructions)
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


@router.post(ONE + "/refine", response_model=AnalysisOut)
async def refine_analysis(
    analysis_id: int,
    body: RefineRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """Amend the plan that is already there. Tasks the model leaves alone keep their wording,
    their refs and whoever edited them, so this is the cheap way to iterate on a moving
    requirement. A refine that fails leaves the plan exactly as it was."""
    row = await _analysis(session, project, analysis_id)
    try:
        await service.refine(session, row, user.email, body.provider, body.model, body.instructions)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_analysis_refine",
        resource_type="kickoff_analysis",
        resource_id=str(row.id),
        project_id=project.id,
        detail={
            "run": row.runs,
            "reader": row.plan["reader"],
            "model": row.plan["model"],
            "tasks": len(row.plan["tasks"]),
            "instructions": body.instructions,
        },
        note="A draft. It counts toward nothing until a named person creates it in the backlog.",
    )
    return await _saved(session, row)


@router.get(ONE + "/runs", response_model=list[RunSummaryOut])
async def list_runs(
    analysis_id: int,
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> list[RunSummaryOut]:
    """Every draft this analysis has had, newest first."""
    row = await _analysis(session, project, analysis_id)
    return [service.run_summary(r, row.runs) for r in await service.runs(session, row)]


@router.get(ONE + "/runs/{number}", response_model=RunDetailOut)
async def read_run(
    analysis_id: int,
    number: int,
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> RunDetailOut:
    """One earlier draft, with what changed since the draft before it."""
    row = await _analysis(session, project, analysis_id)
    records = await service.runs(session, row)
    record = next((r for r in records if r.run_number == number), None)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such run")
    earlier = [r for r in records if r.run_number < number]
    return service.run_detail(row, record, earlier[0] if earlier else None)


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


@router.get(ONE + "/backlog-fields", response_model=BacklogFieldsOut)
async def read_backlog_fields(
    analysis_id: int,
    backlog_url: str,
    project: Project = Depends(require("contributor")),
    session: AsyncSession = Depends(get_session),
) -> BacklogFieldsOut:
    """What the target project offers for each ticket option. Read-only: nothing is written."""
    await _analysis(session, project, analysis_id)
    try:
        return await service.backlog_fields(session, backlog_url)
    except service.Refused as exc:
        raise _refused(exc) from exc


@router.put(ONE + "/backlog-options", response_model=AnalysisOut)
async def write_backlog_options(
    analysis_id: int,
    body: JiraDefaults,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AnalysisOut:
    """What every ticket this analysis creates should carry. Checked against Jira again on create."""
    row = await _analysis(session, project, analysis_id)
    service.set_backlog_options(row, user.email, body)
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
