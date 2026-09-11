from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, require
from app.db.session import get_session
from app.models.evidence import ActionRecord, FeatureEvidence
from app.models.project import Project
from app.schemas.common import RagState
from app.schemas.readiness import Action, FeatureReadiness
from app.services import audit
from app.services.readiness import build, latest_release

router = APIRouter(prefix="/projects", tags=["readiness"])


@router.get("/{project_id}/feature-readiness", response_model=FeatureReadiness)
async def feature_readiness(
    release: str | None = Query(
        None, max_length=32, description="Release to report on. Defaults to the newest tracked."
    ),
    project: Project = Depends(require("viewer")),
    session: AsyncSession = Depends(get_session),
) -> FeatureReadiness:
    release = release or await latest_release(session, project.id)
    payload = await build(session, project, release) if release else None
    if payload is None:
        scope = f"in release {release}" if release else "in any release"
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No feature is tracked for {project.name} {scope}. That is a gap in "
            "tagging, not an empty gate — check the shiftleft-tracked label and fixVersion.",
        )
    return payload


@router.post("/{project_id}/actions/{action_id}/acknowledge", response_model=Action)
async def acknowledge_action(
    action_id: int,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Action:
    """Acknowledgement records a named person and a time. It does not close the signal."""
    action = await session.get(ActionRecord, action_id)
    if action is None or action.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    if action.status == "open":
        action.status = "acknowledged"
        action.acknowledged_by = user.email
        action.acknowledged_at = datetime.now(timezone.utc)
        action.age = "acknowledged just now"
        await audit.record(
            session, actor=user.email, action="acknowledge", resource_type="action_record",
            resource_id=str(action.id), project_id=project.id, detail={"signal": action.signal},
            note="Acknowledged, not resolved — the underlying evidence gap is unchanged.",
        )
        await session.commit()
    return Action(
        id=action.id, signal=action.signal, next_action=action.next_action, owner=action.owner,
        age=action.age, status=action.status, status_label=action.status.capitalize(),
        severity=RagState.of(action.severity, [action.next_action]),
        acknowledged_by=action.acknowledged_by, acknowledged_at=action.acknowledged_at,
    )


@router.post("/{project_id}/features/{feature_key}/ai-draft/accept", response_model=FeatureReadiness)
async def accept_ai_draft(
    feature_key: str = Path(max_length=32),
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FeatureReadiness:
    """AI drafts count toward nothing until a named person accepts them, here and in the audit log."""
    feature = (
        await session.execute(
            select(FeatureEvidence).where(
                FeatureEvidence.project_id == project.id, FeatureEvidence.key == feature_key
            )
        )
    ).scalar_one_or_none()
    if feature is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature not found")
    if not feature.ai_draft:
        raise HTTPException(status.HTTP_409_CONFLICT, "That feature carries no AI draft")
    feature.ai_accepted_by = user.email
    feature.ai_accepted_at = datetime.now(timezone.utc)
    await audit.record(
        session, actor=user.email, action="accept_ai_draft", resource_type="feature_evidence",
        resource_id=feature.key, project_id=project.id,
        detail={"drawn_from": feature.ai_drawn_from},
        note="AI output accepted by a named person; it counted toward nothing before this.",
    )
    await session.commit()
    return await build(session, project, feature.release)
