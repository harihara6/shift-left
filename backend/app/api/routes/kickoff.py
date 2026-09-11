"""Feature Kickoff: take a PRD from Confluence to a checked, tagged plan a named person confirms.

Every endpoint is project-scoped and needs a contributor: kickoff drafts work into the project's
backlog. A session reads the PRD with its actor's own permissions, so it is readable only by
whoever ran it (and platform admins). Anyone else gets a 404 that reveals nothing.

Only `POST …/apply` writes. The confirmation is committed before the first external write, and
in dry-run mode nothing external is written at all.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, require
from app.db.session import get_session
from app.models.kickoff import KickoffSession
from app.models.project import Project
from app.schemas.kickoff import (
    ActionsUpdate,
    Connections,
    FactsUpdate,
    KickoffOut,
    KickoffSummary,
    ModelOptions,
    PlanUpdate,
    PrdList,
    StartRequest,
)
from app.services import audit
from app.services import kickoff as service
from app.services import kickoff_write as writing
from app.services.kickoff_sources import SourceUnavailable

logger = logging.getLogger("shiftleft.kickoff")
router = APIRouter(prefix="/projects", tags=["kickoff"])


def _refused(exc: service.Refused) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"message": exc.message, "blockers": exc.blockers})


def _unavailable(exc: SourceUnavailable) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"A source couldn't be read: {exc}")


async def _own(session: AsyncSession, project: Project, session_id: int, user: CurrentUser) -> KickoffSession:
    row = await session.get(KickoffSession, session_id)
    if (
        row is None or row.project_id != project.id
        or (row.actor != user.email and not user.is_platform_admin)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kickoff not found")
    return row


async def _view(session: AsyncSession, row: KickoffSession, project: Project) -> KickoffOut:
    return service.view(row, project, await service.artifacts(session))


@router.get("/{project_id}/kickoff/prds", response_model=PrdList)
async def list_prds(
    q: str = Query(default="", max_length=120),
    project: Project = Depends(require("contributor")),
) -> PrdList:
    return await service.list_prds(project, q)


@router.get("/{project_id}/kickoff/connections", response_model=Connections)
async def list_connections(project: Project = Depends(require("contributor"))) -> Connections:
    """Where reads and writes go, from configuration. Never returns a credential."""
    return service.connections()


@router.get("/{project_id}/kickoff/models", response_model=ModelOptions)
async def list_models(project: Project = Depends(require("contributor"))) -> ModelOptions:
    """Fetched from each provider at request time; never a hardcoded list."""
    return await service.model_options()


@router.get("/{project_id}/kickoff", response_model=list[KickoffSummary])
async def my_kickoffs(
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[KickoffSummary]:
    rows = (
        await session.execute(
            select(KickoffSession)
            .where(KickoffSession.project_id == project.id, KickoffSession.actor == user.email)
            .order_by(KickoffSession.id.desc())
            .limit(10)
        )
    ).scalars()
    return [
        KickoffSummary(id=r.id, page_title=r.page_title, status=r.status, model=service.drafted_by(r),
                       created_at=service.as_utc(r.created_at), approved_by=r.approved_by)
        for r in rows
    ]


@router.post("/{project_id}/kickoff", response_model=KickoffOut, status_code=status.HTTP_201_CREATED)
async def start(
    body: StartRequest,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffOut:
    """Read the PRD and extract its facts. Creates nothing but the session."""
    try:
        row = await service.start(session, project, user.email, body.page_id, body.provider, body.model)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PRD page not found") from exc
    except service.Refused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    except SourceUnavailable as exc:
        raise _unavailable(exc) from exc
    await session.flush()
    await audit.record(
        session, actor=user.email, action="kickoff_start", resource_type="kickoff_session",
        resource_id=str(row.id), project_id=project.id,
        detail={"page_id": row.page_id, "page_version": row.page_version, "provider": row.provider,
                "model": row.model, "reader": row.reader, "sources": row.data["source_mode"]},
        note="Read-only: the PRD was read and its facts extracted. Nothing was written anywhere.",
    )
    await session.commit()
    await session.refresh(row)
    return await _view(session, row, project)


@router.get("/{project_id}/kickoff/{session_id}", response_model=KickoffOut)
async def get_kickoff(
    session_id: int,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffOut:
    return await _view(session, await _own(session, project, session_id, user), project)


@router.put("/{project_id}/kickoff/{session_id}/facts", response_model=KickoffOut)
async def update_facts(
    session_id: int,
    body: FactsUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffOut:
    """A person correcting what was read. Every rule re-resolves from the corrected facts."""
    row = await _own(session, project, session_id, user)
    try:
        service.update_facts(row, body.facts, user.email)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await session.commit()
    await session.refresh(row)
    return await _view(session, row, project)


@router.put("/{project_id}/kickoff/{session_id}/actions", response_model=KickoffOut)
async def choose_actions(
    session_id: int,
    body: ActionsUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffOut:
    """Record what to do and run the selected checks. Leaving a recommended action out needs a reason."""
    row = await _own(session, project, session_id, user)
    try:
        await service.choose(row, body.choices)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await session.commit()
    await session.refresh(row)
    return await _view(session, row, project)


@router.put("/{project_id}/kickoff/{session_id}/plan", response_model=KickoffOut)
async def decide(
    session_id: int,
    body: PlanUpdate,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffOut:
    row = await _own(session, project, session_id, user)
    try:
        service.decide(row, project, await service.artifacts(session), body)
    except service.Refused as exc:
        raise _refused(exc) from exc
    await session.commit()
    await session.refresh(row)
    return await _view(session, row, project)


@router.post("/{project_id}/kickoff/{session_id}/apply", response_model=KickoffOut)
async def apply(
    session_id: int,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffOut:
    """The confirmation, then the writes. Also the retry, for a plan whose items partly failed.

    Order matters: preflight (nothing written if it fails), then the confirmation and the frozen
    plan are committed, then the writes run and every item's result is recorded.
    """
    row = await _own(session, project, session_id, user)
    defs = await service.artifacts(session)
    try:
        plan, previous = service.prepare_apply(row, project, defs)
    except service.Refused as exc:
        raise _refused(exc) from exc
    items = plan["items"]
    writer = writing.writer(service.write_mode())
    context = service.write_context(row, project, defs, user.email)
    problems = await writer.preflight(items, context)
    if problems:
        raise _refused(service.Refused("Nothing was written: fix these first.", problems))
    retry = bool(previous)
    try:
        await service.claim(session, row, user.email, plan, writer.mode)
    except service.Refused as exc:
        await session.rollback()
        raise _refused(exc) from exc
    await session.commit()

    try:
        results = await writer.apply(items, previous, service.write_context(row, project, defs, user.email))
    except Exception as exc:  # the writer broke: record what is known rather than leave it "applying"
        logger.exception("Kickoff %s: the writer stopped", row.id)
        reason = f"the apply stopped unexpectedly ({type(exc).__name__})."
        results = service.interrupted(items, previous, reason)
    summary = service.finish_apply(row, items, results)
    await audit.record(
        session, actor=user.email, action="kickoff_retry" if retry else "kickoff_apply",
        resource_type="kickoff_session", resource_id=str(row.id), project_id=project.id,
        detail={**summary, "page_id": row.page_id, "page_version": row.page_version,
                "model": row.model, "reader": row.reader},
        note=(
            "A drafted plan counts toward nothing until a named person confirms it. This entry is "
            + ("a retry of the failed items of that confirmed plan." if retry else "that confirmation.")
            + (" Dry run: nothing was written to Jira, Xray or Confluence." if writer.mode == "dry-run" else
               " Live: results per item are on the kickoff.")
        ),
    )
    await session.commit()
    await session.refresh(row)
    return await _view(session, row, project)
