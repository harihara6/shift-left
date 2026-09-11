"""Creating and describing projects.

Both the manual form (POST /projects) and guided onboarding create projects, and they have to
agree on the rules: the same id for the same name, and the creator as the first admin so a
project is never created unreachable. Both go through `create` so neither can drift.
"""

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.project import Project, ProjectAccess
from app.models.template import ProjectTemplate
from app.schemas.settings import AccessGrant, ProjectDetail, ProjectSummary

KEY_MAX = 16


def slugify(name: str) -> str:
    """Project ids appear in URLs, so they are lower-case and hyphenated."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def dashboard_counts(session: AsyncSession, project_ids: list[str]) -> dict[str, int]:
    """Enabled templates per project. Every enabled template is one dashboard."""
    if not project_ids:
        return {}
    rows = await session.execute(
        select(ProjectTemplate.project_id, func.count())
        .where(ProjectTemplate.project_id.in_(project_ids), ProjectTemplate.enabled.is_(True))
        .group_by(ProjectTemplate.project_id)
    )
    return {project_id: count for project_id, count in rows.all()}


def summary(project: Project, dashboards: int) -> ProjectSummary:
    return ProjectSummary(
        id=project.id, key=project.key, name=project.name, owner=project.owner,
        created_on=project.created_on, dashboards=dashboards,
        archived=project.archived_at is not None,
    )


async def detail(session: AsyncSession, project_id: str) -> ProjectDetail:
    """Re-read with grants loaded eagerly - an expired instance would lazy-load them outside
    the async context."""
    project = (
        await session.execute(
            select(Project)
            .options(selectinload(Project.access))
            .where(Project.id == project_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    counts = await dashboard_counts(session, [project.id])
    return ProjectDetail(
        **summary(project, counts.get(project.id, 0)).model_dump(),
        access=[AccessGrant.model_validate(a) for a in project.access],
    )


async def create(
    session: AsyncSession, *, key: str, name: str, owner: str, creator: str
) -> Project:
    """Add a project and make its creator the admin. Caller commits.

    Raises 409 when the id is taken. A key collision surfaces as an IntegrityError at commit,
    which callers turn into a 409 of their own.
    """
    project_id = slugify(name)
    if not project_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A project name needs at least one letter or digit"
        )
    if await session.get(Project, project_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A project with that name already exists")
    project = Project(
        id=project_id, key=key, name=name, owner=owner,
        created_on=datetime.now(timezone.utc).date(),
    )
    session.add(project)
    # The creator gets admin on their own project, so a project is never created unreachable.
    session.add(
        ProjectAccess(project_id=project_id, principal=creator, role="admin",
                      via="Explicit grant", granted_by=creator)
    )
    await session.flush()
    return project


async def free_copy_key(session: AsyncSession, key: str) -> str:
    """A project key for a duplicate that fits the 16-character limit and is not yet taken."""
    taken = set((await session.execute(select(Project.key))).scalars().all())
    for suffix in ["C", *(f"C{n}" for n in range(2, 100))]:
        candidate = f"{key[: KEY_MAX - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
    raise HTTPException(status.HTTP_409_CONFLICT, "No free project key for another copy")
