from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

# Access grants and credential changes are retained far longer than ordinary dashboard edits.
RETENTION = {"dashboard": 365, "connector": 730, "access": 2555, "credential": 2555}


async def record(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    category: str = "dashboard",
    project_id: str | None = None,
    detail: dict | None = None,
    note: str = "",
) -> None:
    """Append-only. Never call this with a secret value in `detail`."""
    session.add(
        AuditLog(
            actor=actor,
            action=action,
            category=category,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            detail=detail or {},
            retention_days=RETENTION.get(category, 365),
            note=note,
        )
    )
