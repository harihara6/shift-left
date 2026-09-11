"""Enabling a catalog template on a project.

One implementation, because product rule 7 lives here: enabling deep-copies, and after the
copy there is no runtime coupling at all. Both the Settings toggle and guided onboarding go
through this function so neither can drift into a shallow reference.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.template import ProjectTemplate, Template, WidgetBinding


async def enable(session: AsyncSession, project_id: str, template: Template) -> ProjectTemplate:
    """Deep-copy `template` into `project_id`, or re-enable the copy already there.

    Re-enabling keeps the project's own edited bindings rather than copying over them — the
    edits are the project's, not the catalog's. Caller commits.
    """
    row = (
        await session.execute(
            select(ProjectTemplate)
            .options(selectinload(ProjectTemplate.widgets))
            .where(
                ProjectTemplate.project_id == project_id,
                ProjectTemplate.template_key == template.key,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = ProjectTemplate(
            project_id=project_id, template_key=template.key, name=template.name,
            perspective=template.perspective, enabled=True, copied_from_version=template.version,
            copied_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
    else:
        row.enabled = True

    existing = (
        await session.execute(
            select(WidgetBinding.id).where(WidgetBinding.project_template_id == row.id)
        )
    ).first()
    if existing is not None:
        return row

    # First enable: copy the catalog's widgets in. Origin metadata is traceability only.
    catalog = (
        await session.execute(
            select(Template).options(selectinload(Template.widgets)).where(Template.key == template.key)
        )
    ).scalar_one()
    row.copied_from_version = catalog.version
    row.copied_at = datetime.now(timezone.utc)
    for widget in catalog.widgets:
        session.add(
            WidgetBinding(
                project_template_id=row.id, position=widget.position, name=widget.name,
                connector_key=widget.connector_key, query=widget.query,
                refresh_interval=widget.refresh_interval, drill_template=widget.drill_template,
                guide_key=widget.guide_key,
            )
        )
    return row
