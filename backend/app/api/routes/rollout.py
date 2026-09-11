from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, require
from app.db.session import get_session
from app.models.project import Project
from app.models.rollout import STAGES, RolloutState
from app.schemas.rollout import RolloutBoard, StageChange
from app.services import audit, calendar_context
from app.services import rollout as service
from app.services.rollout_rules import STAGE_LABELS

router = APIRouter(prefix="/projects", tags=["rollout"])

NOT_ENROLLED = (
    "{name} is not enrolled in the shift-left rollout. That is a gap, not a pass — nothing is "
    "detecting its evidence yet."
)


async def _enrolled(session: AsyncSession, project: Project) -> RolloutState:
    state = await service.state_for(session, project)
    if state is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_ENROLLED.format(name=project.name))
    return state


async def _board(session: AsyncSession, project: Project) -> RolloutBoard:
    board = await service.build(session, project)
    if board is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_ENROLLED.format(name=project.name))
    return board


@router.get("/{project_id}/rollout", response_model=RolloutBoard)
async def rollout_board(
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> RolloutBoard:
    return await _board(session, project)


@router.post("/{project_id}/rollout/signoff", response_model=RolloutBoard)
async def record_signoff(
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RolloutBoard:
    """The team agrees the warnings' reasons are fair. A named person, a time, an audit entry."""
    state = await _enrolled(session, project)
    if state.stage != 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Team sign-off is an exit criterion for Warn. {project.name} is at "
            f"{STAGE_LABELS[state.stage]}.",
        )
    state.team_signoff_by = user.email
    state.team_signoff_at = datetime.now(timezone.utc)
    await audit.record(
        session, actor=user.email, action="rollout_signoff", resource_type="rollout_state",
        resource_id=project.id, project_id=project.id,
        detail={"stage": STAGES[state.stage], "policy_version": state.policy_version},
        note="The team agrees the warnings' reasons are fair. Other criteria still apply.",
    )
    await session.commit()
    return await _board(session, project)


@router.post("/{project_id}/rollout/advance", response_model=RolloutBoard)
async def advance_stage(
    body: StageChange,
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RolloutBoard:
    """Only when every exit criterion is met. The refusal lists what is not, as data."""
    state = await _enrolled(session, project)
    if state.stage == len(STAGES) - 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "Hard gate is the final stage.", "blockers": []},
        )
    open_items = service.blockers(await service.criteria(session, project, state))
    if open_items:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": f"{project.name} can't leave {STAGE_LABELS[state.stage]} yet.",
                "blockers": open_items,
            },
        )
    before = state.stage
    state.stage += 1
    state.stage_since = calendar_context.today()
    # Sign-off belongs to the stage it was given for.
    state.team_signoff_by = None
    state.team_signoff_at = None
    await audit.record(
        session, actor=user.email, action="rollout_advance", resource_type="rollout_state",
        resource_id=project.id, project_id=project.id,
        detail={"from": STAGES[before], "to": STAGES[state.stage], "note": body.note},
        note=f"Advanced to {STAGE_LABELS[state.stage]} with every exit criterion met.",
    )
    await session.commit()
    return await _board(session, project)


@router.post("/{project_id}/rollout/rollback", response_model=RolloutBoard)
async def rollback_stage(
    body: StageChange,
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RolloutBoard:
    """Always allowed, never silent: a rollback records who and why."""
    state = await _enrolled(session, project)
    if state.stage == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Observe is the first stage.")
    if not body.note.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Say why you're rolling back. It goes in the audit log."
        )
    before = state.stage
    state.stage -= 1
    state.stage_since = calendar_context.today()
    state.team_signoff_by = None
    state.team_signoff_at = None
    await audit.record(
        session, actor=user.email, action="rollout_rollback", resource_type="rollout_state",
        resource_id=project.id, project_id=project.id,
        detail={"from": STAGES[before], "to": STAGES[state.stage], "note": body.note.strip()},
        note=f"Rolled back to {STAGE_LABELS[state.stage]}.",
    )
    await session.commit()
    return await _board(session, project)
