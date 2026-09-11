
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.registry import get_connector
from app.core.security import CurrentUser, current_user, require
from app.db.session import get_session
from app.models.connector import ConnectorInstance, ConnectorType
from app.models.project import Project
from app.models.template import ProjectTemplate, Template, WidgetBinding
from app.schemas.settings import (
    ProjectTemplateOut,
    QueryPreview,
    TemplateToggle,
    WidgetBindingOut,
    WidgetBindingWrite,
)
from app.services import audit, templating
from app.services.freshness import resolve

router = APIRouter(prefix="/projects/{project_id}/templates", tags=["templates"])


async def _connector_names(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(ConnectorType.key, ConnectorType.name))).all()
    return dict(rows)


def _binding_out(widget: WidgetBinding, names: dict[str, str], stale_keys: set[str]) -> WidgetBindingOut:
    return WidgetBindingOut(
        id=widget.id,
        name=widget.name,
        connector_key=widget.connector_key,
        connector_name=names.get(widget.connector_key, widget.connector_key),
        query=widget.query,
        refresh_interval=widget.refresh_interval,
        drill_template=widget.drill_template,
        last_sync=widget.last_sync,
        stale=widget.connector_key in stale_keys,
        guide_key=widget.guide_key,
    )


@router.get("", response_model=list[ProjectTemplateOut])
async def list_project_templates(
    project: Project = Depends(require("viewer")), session: AsyncSession = Depends(get_session)
) -> list[ProjectTemplateOut]:
    catalog = (await session.execute(select(Template))).scalars().all()
    enabled = {
        t.template_key: t
        for t in (
            await session.execute(
                select(ProjectTemplate)
                .options(selectinload(ProjectTemplate.widgets))
                .where(ProjectTemplate.project_id == project.id)
            )
        ).scalars().all()
    }
    names = await _connector_names(session)
    all_keys = sorted({w.connector_key for t in enabled.values() for w in t.widgets})
    freshness = await resolve(session, all_keys) if all_keys else None
    stale_keys = {c.key for c in freshness.connectors if c.stale} if freshness else set()

    out: list[ProjectTemplateOut] = []
    for template in catalog:
        row = enabled.get(template.key)
        if row is None:
            out.append(
                ProjectTemplateOut(
                    template_key=template.key, name=template.name,
                    perspective=template.perspective, enabled=False,
                )
            )
            continue
        out.append(
            ProjectTemplateOut(
                id=row.id, template_key=row.template_key, name=row.name,
                perspective=row.perspective, enabled=row.enabled,
                copied_from_version=row.copied_from_version, copied_at=row.copied_at,
                widgets=[_binding_out(w, names, stale_keys) for w in row.widgets],
            )
        )
    return out


@router.put("/{template_key}", response_model=ProjectTemplateOut)
async def toggle_template(
    template_key: str,
    body: TemplateToggle,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectTemplateOut:
    """Enabling deep-copies the template into the project.

    After the copy there is no runtime coupling: later edits to the catalog template never reach
    this project, and origin metadata is kept for traceability only.
    """
    template = await session.get(Template, template_key)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    row = (
        await session.execute(
            select(ProjectTemplate)
            .options(selectinload(ProjectTemplate.widgets))
            .where(
                ProjectTemplate.project_id == project.id,
                ProjectTemplate.template_key == template_key,
            )
        )
    ).scalar_one_or_none()

    if not body.enabled:
        if row is not None:
            row.enabled = False
        await audit.record(
            session, actor=user.email, action="disable_template", resource_type="project_template",
            resource_id=template_key, project_id=project.id,
        )
        await session.commit()
        return ProjectTemplateOut(
            id=row.id if row else None, template_key=template_key, name=template.name,
            perspective=template.perspective, enabled=False,
        )

    row = await templating.enable(session, project.id, template)

    await audit.record(
        session, actor=user.email, action="enable_template", resource_type="project_template",
        resource_id=template_key, project_id=project.id,
        detail={"copied_from_version": row.copied_from_version},
        note="Deep copy — later template edits never reach this project.",
    )
    await session.commit()
    refreshed = (
        await session.execute(
            select(ProjectTemplate)
            .options(selectinload(ProjectTemplate.widgets))
            .where(ProjectTemplate.id == row.id)
        )
    ).scalar_one()
    names = await _connector_names(session)
    return ProjectTemplateOut(
        id=refreshed.id, template_key=refreshed.template_key, name=refreshed.name,
        perspective=refreshed.perspective, enabled=refreshed.enabled,
        copied_from_version=refreshed.copied_from_version, copied_at=refreshed.copied_at,
        widgets=[_binding_out(w, names, set()) for w in refreshed.widgets],
    )


async def _load_binding(session: AsyncSession, project_id: str, widget_id: int) -> WidgetBinding:
    widget = await session.get(WidgetBinding, widget_id)
    if widget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Widget binding not found")
    parent = await session.get(ProjectTemplate, widget.project_template_id)
    if parent is None or parent.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Widget binding not found")
    return widget


@router.patch("/widgets/{widget_id}", response_model=WidgetBindingOut)
async def update_binding(
    widget_id: int,
    body: WidgetBindingWrite,
    project: Project = Depends(require("contributor")),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> WidgetBindingOut:
    widget = await _load_binding(session, project.id, widget_id)
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(widget, field, value)
    await audit.record(
        session, actor=user.email, action="update_binding", resource_type="widget_binding",
        resource_id=str(widget_id), project_id=project.id, detail={"fields": sorted(changes)},
    )
    await session.commit()
    return _binding_out(widget, await _connector_names(session), set())


@router.post("/widgets/{widget_id}/preview", response_model=QueryPreview)
async def preview_binding(
    widget_id: int,
    project: Project = Depends(require("contributor")),
    session: AsyncSession = Depends(get_session),
) -> QueryPreview:
    """Runs the bound query through the connector's preview and returns what it would touch.

    An empty result is reported as empty. It is never rendered as a healthy zero.
    """
    widget = await _load_binding(session, project.id, widget_id)
    ctype = await session.get(ConnectorType, widget.connector_key)
    if ctype is None:
        return QueryPreview(
            connector_key=widget.connector_key, query=widget.query, ok=False,
            note=f"No connector of type '{widget.connector_key}' is registered — this widget cannot resolve.",
        )
    instance = (
        await session.execute(
            select(ConnectorInstance).where(ConnectorInstance.connector_key == widget.connector_key)
        )
    ).scalars().first()
    if instance is None or instance.state in ("not_configured", "disabled"):
        return QueryPreview(
            connector_key=widget.connector_key, query=widget.query, ok=False,
            note=f"{ctype.name} is not connected — the widget renders as a gap, not as zero.",
        )
    connector = get_connector(ctype.key, ctype.name, instance.config, instance.secret_refs)
    rows = await connector.preview_data(widget.query, limit=10)
    freshness = await resolve(session, [ctype.key])
    return QueryPreview(
        connector_key=ctype.key,
        query=widget.query,
        ok=True,
        rows=rows,
        row_count=len(rows),
        stale=freshness.stale,
        note=freshness.note or (f"{len(rows)} sample records" if rows else "Query matched nothing."),
    )
