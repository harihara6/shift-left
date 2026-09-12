"""Service-wide Feature Kickoff defaults.

Like connectors, these belong to no single project, so project roles cannot govern them. The split
is deliberate and differs from the connector one only in what is at stake: this row holds no
credential, so any signed-in user may read it - the wizard fills a new analysis in from it and has
to be able to. Only a platform admin may change it, and every change is audited.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user, require_platform_admin
from app.db.session import get_session
from app.schemas.kickoff import KickoffSettingsOut, KickoffSettingsWrite
from app.services import audit
from app.services import kickoff_settings as service

router = APIRouter(prefix="/kickoff/settings", tags=["kickoff"])


@router.get("", response_model=KickoffSettingsOut)
async def read_settings(
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> KickoffSettingsOut:
    return service.view(await service.load(session), editable=user.is_platform_admin)


@router.put("", response_model=KickoffSettingsOut)
async def write_settings(
    body: KickoffSettingsWrite,
    user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> KickoffSettingsOut:
    row = await service.load(session)
    service.write(row, body, user.email)
    # Flushed and re-read before the response is built: `updated_at` is set by the database, and
    # committing first would leave it expired with no way to load it back here.
    await session.flush()
    await session.refresh(row)
    result = service.view(row, editable=True)
    await audit.record(
        session,
        actor=user.email,
        action="kickoff_settings_update",
        resource_type="kickoff_settings",
        resource_id="1",
        category="configuration",
        detail={
            "tdd_template_url": row.tdd_template_url,
            "tdd_space_key": row.tdd_space_key,
            "tdd_sections": row.tdd_sections,
            "jira_project_url": row.jira_project_url,
            "jira_defaults": row.jira_defaults,
            "has_analysis_prompt": bool(row.analysis_prompt),
            "has_tdd_prompt": bool(row.tdd_prompt),
        },
        note="Defaults for new analyses. Nothing already under way is changed.",
    )
    await session.commit()
    return result
