from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import CurrentUser, current_user, require, visible_projects
from app.db.session import get_session
from app.models.project import Project, ProjectAccess
from app.models.template import ProjectTemplate, WidgetBinding
from app.schemas.settings import (
    AccessGrant,
    AccessGrantWrite,
    ProjectDetail,
    ProjectRename,
    ProjectSummary,
    ProjectWrite,
)
from app.services import audit
from app.services import projects as service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
async def list_projects(
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> list[ProjectSummary]:
    """Only the projects this caller may see. The list itself is authorization-scoped."""
    projects = await visible_projects(session, user)
    counts = await service.dashboard_counts(session, [p.id for p in projects])
    return [service.summary(p, counts.get(p.id, 0)) for p in projects]


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectWrite,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectDetail:
    try:
        project = await service.create(
            session, key=body.key, name=body.name, owner=body.owner, creator=user.email
        )
        await audit.record(
            session, actor=user.email, action="create", resource_type="project",
            resource_id=project.id, project_id=project.id, detail={"key": body.key},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Project key already in use") from exc
    return await service.detail(session, project.id)


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project: Project = Depends(require("viewer")), session: AsyncSession = Depends(get_session)
) -> ProjectDetail:
    return await service.detail(session, project.id)


@router.patch("/{project_id}", response_model=ProjectDetail)
async def rename_project(
    body: ProjectRename,
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectDetail:
    """Renames the project in place. The id is not re-minted, so links and grants survive."""
    before = project.name
    project.name = body.name.strip()
    await audit.record(
        session, actor=user.email, action="rename", resource_type="project",
        resource_id=project.id, project_id=project.id, detail={"from": before, "to": project.name},
    )
    await session.commit()
    return await service.detail(session, project.id)


@router.post("/{project_id}/duplicate", response_model=ProjectDetail, status_code=201)
async def duplicate_project(
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectDetail:
    """Copies the project's templates and their bindings. Access grants are not copied -
    who may see a new project is always an explicit decision."""
    source = (
        await session.execute(
            select(ProjectTemplate)
            .options(selectinload(ProjectTemplate.widgets))
            .where(ProjectTemplate.project_id == project.id)
        )
    ).scalars().all()
    try:
        copy = await service.create(
            session, key=await service.free_copy_key(session, project.key),
            name=f"{project.name} (copy)", owner=project.owner, creator=user.email,
        )
        now = datetime.now(timezone.utc)
        for template in source:
            copied = ProjectTemplate(
                project_id=copy.id, template_key=template.template_key, name=template.name,
                perspective=template.perspective, enabled=template.enabled,
                copied_from_version=template.copied_from_version,
                copied_at=now if template.enabled else None,
            )
            session.add(copied)
            await session.flush()
            for widget in template.widgets:
                session.add(
                    WidgetBinding(
                        project_template_id=copied.id, position=widget.position, name=widget.name,
                        connector_key=widget.connector_key, query=widget.query,
                        refresh_interval=widget.refresh_interval,
                        drill_template=widget.drill_template, guide_key=widget.guide_key,
                    )
                )
        await audit.record(
            session, actor=user.email, action="duplicate", resource_type="project",
            resource_id=copy.id, project_id=copy.id, detail={"source": project.id},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A copy of this project already exists") from exc
    return await service.detail(session, copy.id)


@router.post("/{project_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft delete. Dashboards go with it; the audit trail stays."""
    project.archived_at = datetime.now(timezone.utc)
    await audit.record(
        session, actor=user.email, action="archive", resource_type="project",
        resource_id=project.id, project_id=project.id,
        note="Soft delete — dashboards hidden, audit trail retained.",
    )
    await session.commit()


@router.get("/{project_id}/access", response_model=list[AccessGrant])
async def list_access(
    project: Project = Depends(require("viewer")), session: AsyncSession = Depends(get_session)
) -> list[AccessGrant]:
    grants = (
        await session.execute(
            select(ProjectAccess).where(ProjectAccess.project_id == project.id)
            .order_by(ProjectAccess.principal)
        )
    ).scalars().all()
    return [AccessGrant.model_validate(g) for g in grants]


@router.post("/{project_id}/access", response_model=AccessGrant, status_code=201)
async def add_grant(
    body: AccessGrantWrite,
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AccessGrant:
    grant = ProjectAccess(
        project_id=project.id, principal=body.principal, role=body.role, via=body.via,
        granted_by=user.email,
    )
    session.add(grant)
    await audit.record(
        session, actor=user.email, action="grant", category="access", resource_type="project_access",
        resource_id=body.principal, project_id=project.id,
        detail={"role": body.role, "via": body.via},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That principal already has a grant") from exc
    return AccessGrant.model_validate(grant)


@router.delete("/{project_id}/access/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(
    grant_id: int,
    project: Project = Depends(require("admin")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    grant = await session.get(ProjectAccess, grant_id)
    if grant is None or grant.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    if grant.role == "admin":
        other_admins = (
            await session.execute(
                select(ProjectAccess.id).where(
                    ProjectAccess.project_id == project.id,
                    ProjectAccess.role == "admin",
                    ProjectAccess.id != grant_id,
                )
            )
        ).first()
        if other_admins is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "A project cannot be left without an admin"
            )
    await session.delete(grant)
    await audit.record(
        session, actor=user.email, action="revoke", category="access",
        resource_type="project_access", resource_id=grant.principal, project_id=project.id,
        detail={"role": grant.role},
    )
    await session.commit()
