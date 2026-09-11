"""Service-wide connector configuration.

Connectors belong to no single project, so project roles cannot govern them. Any signed-in user
may read how a connector is set up (secrets excepted - there is no read path for those); only a
platform admin may change one, and every change is audited.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.registry import get_connector
from app.core.security import CurrentUser, current_user, require_platform_admin
from app.db.session import get_session
from app.models.connector import ConnectorInstance, ConnectorType
from app.schemas.settings import (
    ConnectorAuthMethod,
    ConnectorConfigWrite,
    ConnectorDetail,
    ConnectorField,
    ConnectorSummary,
    ConnectorTestResult,
    SecretRotate,
)
from app.services import audit
from app.services.freshness import age_minutes, humanize_age, resolve

router = APIRouter(prefix="/connectors", tags=["connectors"])

STATE_LABEL = {
    "connected": "Connected", "stale": "Stale", "disabled": "Disabled",
    "not_configured": "Not configured", "error": "Error",
}

# States in which an instance contributes nothing - a gap, not a healthy zero.
INACTIVE = ("not_configured", "disabled")

# Shown in place of a credential. There is no endpoint that returns a secret value.
VAULT_PLACEHOLDER = "•••••••• stored in vault"


async def _type_or_404(session: AsyncSession, key: str) -> ConnectorType:
    ctype = await session.get(ConnectorType, key)
    if ctype is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connector not found")
    return ctype


async def _instance_for(session: AsyncSession, key: str) -> ConnectorInstance | None:
    return (
        await session.execute(
            select(ConnectorInstance)
            .where(ConnectorInstance.connector_key == key)
            .order_by(ConnectorInstance.id)
        )
    ).scalars().first()


async def _instance_or_new(session: AsyncSession, ctype: ConnectorType) -> ConnectorInstance:
    instance = await _instance_for(session, ctype.key)
    if instance is None:
        instance = ConnectorInstance(connector_key=ctype.key, label=ctype.name, config={}, secret_refs={})
        session.add(instance)
    return instance


def _is_active(instance: ConnectorInstance | None) -> bool:
    return instance is not None and instance.state not in INACTIVE


def _secret_keys(ctype: ConnectorType) -> set[str]:
    return {f["key"] for f in ctype.fields if f["type"] == "secret"}


def _summary(ctype: ConnectorType, instance: ConnectorInstance | None, stale: bool) -> ConnectorSummary:
    state = instance.state if instance else "not_configured"
    if stale and state == "connected":
        # Freshness overrides a stored state: a connector past its threshold reads Stale.
        state = "stale"
    last = instance.last_successful_sync if instance else None
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return ConnectorSummary(
        key=ctype.key, name=ctype.name, category=ctype.category, state=state,
        state_label=STATE_LABEL.get(state, state), last_successful_sync=last,
        sync_label=humanize_age(age_minutes(last)) if last else "—",
        instances=1 if _is_active(instance) else 0,
        stale=stale,
    )


async def _detail(session: AsyncSession, ctype: ConnectorType) -> ConnectorDetail:
    instance = await _instance_for(session, ctype.key)
    freshness = await resolve(session, [ctype.key])
    summary = _summary(ctype, instance, stale=_is_active(instance) and freshness.stale)

    fields = []
    for field in ctype.fields:
        is_secret = field["type"] == "secret"
        stored = (instance.config.get(field["key"]) if instance else None) or field.get("seed_value")
        fields.append(
            ConnectorField(
                key=field["key"],
                label=field["label"],
                help=field["help"],
                type=field["type"],
                # Write-only: a secret comes back as a placeholder, never as a value.
                value=None if is_secret else stored,
                placeholder=VAULT_PLACEHOLDER if is_secret else "",
            )
        )

    return ConnectorDetail(
        **summary.model_dump(),
        description=ctype.description,
        auth_methods=[ConnectorAuthMethod(**a) for a in ctype.auth_methods],
        selected_auth=instance.auth_method if instance else None,
        fields=fields,
        scopes=ctype.scopes,
        rate_limits=ctype.rate_limits,
        staleness_minutes=ctype.staleness_minutes,
        status_only=ctype.status_only,
    )


@router.get("", response_model=list[ConnectorSummary])
async def list_connectors(
    _: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> list[ConnectorSummary]:
    types = (
        await session.execute(
            select(ConnectorType).order_by(ConnectorType.category, ConnectorType.name)
        )
    ).scalars().all()
    instances: dict[str, ConnectorInstance] = {}
    for instance in (
        await session.execute(select(ConnectorInstance).order_by(ConnectorInstance.id))
    ).scalars().all():
        instances.setdefault(instance.connector_key, instance)
    freshness = await resolve(session, [t.key for t in types])
    stale_keys = {c.key for c in freshness.connectors if c.stale}
    return [
        _summary(
            ctype, instances.get(ctype.key),
            stale=_is_active(instances.get(ctype.key)) and ctype.key in stale_keys,
        )
        for ctype in types
    ]


@router.get("/{connector_key}", response_model=ConnectorDetail)
async def get_connector_detail(
    connector_key: str,
    _: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ConnectorDetail:
    """The config form is built from this response — each connector declares its own field set."""
    return await _detail(session, await _type_or_404(session, connector_key))


@router.put("/{connector_key}", response_model=ConnectorDetail)
async def update_connector(
    connector_key: str,
    body: ConnectorConfigWrite,
    user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> ConnectorDetail:
    ctype = await _type_or_404(session, connector_key)
    if _secret_keys(ctype) & set(body.config):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Credentials are written through /secrets, never through the config body",
        )
    unknown = set(body.config) - {f["key"] for f in ctype.fields}
    if unknown:
        # The form is data-driven from the connector's own field set; nothing else is stored.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{ctype.name} has no field named {', '.join(sorted(unknown))}",
        )
    if body.auth_method and body.auth_method not in {a["label"] for a in ctype.auth_methods}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{ctype.name} does not support '{body.auth_method}'"
        )
    instance = await _instance_or_new(session, ctype)
    instance.config = {**(instance.config or {}), **body.config}
    if body.auth_method:
        instance.auth_method = body.auth_method
    if instance.state == "not_configured" and instance.config and instance.secret_refs:
        instance.state = "connected"
    await audit.record(
        session, actor=user.email, action="update", category="connector",
        resource_type="connector_instance", resource_id=connector_key,
        # Field names only. Values can carry tenant URLs; the instance row is the record of those.
        detail={"fields": sorted(body.config), "auth_method": body.auth_method},
    )
    await session.commit()
    return await _detail(session, ctype)


@router.post("/{connector_key}/secrets", status_code=status.HTTP_204_NO_CONTENT)
async def rotate_secret(
    connector_key: str,
    body: SecretRotate,
    user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Write-only. The value goes to the vault; this service stores only the reference.

    Nothing here logs, echoes or persists `body.value`.
    """
    ctype = await _type_or_404(session, connector_key)
    if body.field_key not in _secret_keys(ctype):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a credential field")
    instance = await _instance_or_new(session, ctype)
    # A real vault write happens here. The reference is all that is kept.
    instance.secret_refs = {
        **(instance.secret_refs or {}),
        body.field_key: f"vault://shiftleft/{connector_key}/{body.field_key}",
    }
    await audit.record(
        session, actor=user.email, action="rotate_credential", category="credential",
        resource_type="connector_instance", resource_id=connector_key,
        detail={"field": body.field_key}, note="Value never stored by this service.",
    )
    await session.commit()


@router.post("/{connector_key}/test", response_model=ConnectorTestResult)
async def test_connector(
    connector_key: str,
    user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> ConnectorTestResult:
    """Reaches out to the source with the service's credentials, so it is an admin action."""
    ctype = await _type_or_404(session, connector_key)
    instance = await _instance_for(session, connector_key)
    connector = get_connector(
        ctype.key, ctype.name,
        instance.config if instance else {},
        instance.secret_refs if instance else {},
    )
    result = await connector.test_connection()
    if instance is not None:
        instance.last_error = None if result.ok else result.message
    await audit.record(
        session, actor=user.email, action="test_connection", category="connector",
        resource_type="connector_instance", resource_id=connector_key, detail={"ok": result.ok},
    )
    await session.commit()
    return ConnectorTestResult(
        ok=result.ok, message=result.message, capabilities=result.capabilities,
        filters=result.filters, checked_at=datetime.now(timezone.utc),
    )


@router.post("/{connector_key}/toggle", response_model=ConnectorSummary)
async def toggle_connector(
    connector_key: str,
    user: CurrentUser = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> ConnectorSummary:
    ctype = await _type_or_404(session, connector_key)
    instance = await _instance_or_new(session, ctype)
    instance.state = "connected" if instance.state == "disabled" else "disabled"
    await audit.record(
        session, actor=user.email, action="toggle", category="connector",
        resource_type="connector_instance", resource_id=connector_key,
        detail={"state": instance.state},
    )
    await session.commit()
    freshness = await resolve(session, [connector_key])
    return _summary(ctype, instance, stale=instance.state == "connected" and freshness.stale)
