"""Service-wide connector configuration.

Connectors belong to no single project, so project roles cannot govern them. Any signed-in user
may read how a connector is set up (secrets excepted - there is no read path for those); only a
platform admin may change one, and every change is audited.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.registry import SHARED_CREDENTIALS, get_connector
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
from app.services import audit, vault
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
NOT_STORED = "Not set: nothing stored yet"
# The database travels between machines; the key that decrypts its secrets does not. So a stored
# secret that won't decrypt is not a fault - it is the expected state on a machine this credential
# was never typed into, and saying which it is turns "why is this broken" into one obvious action.
FROM_ANOTHER_MACHINE = "Set on another machine: it can't be read here, so enter it again"


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


# The connector whose credential another one uses (SHARED_CREDENTIALS), and its instance.
Shared = tuple[ConnectorType | None, ConnectorInstance | None]


async def _has_credential(
    ctype: ConnectorType, instance: ConnectorInstance | None, shared: Shared | None = None,
) -> bool:
    """Whether a credential this connector declares actually resolves in the vault.

    A stored "connected" state is only a label - seeded from the prototype, or left over from an
    auth method this service no longer offers. Without a credential nothing can be read, so the
    connector reads Not configured however it is labelled (product rule 1). A connector that
    shares another's connection (SHARED_CREDENTIALS) is judged by that one.
    """
    if shared is not None:
        ctype, instance = shared
        if ctype is None:
            return False
    needed = _secret_keys(ctype)
    if not needed:
        return True
    refs = (instance.secret_refs or {}) if instance else {}
    for key in needed:
        ref = refs.get(key)
        if ref and await vault.read(ref):
            return True
    return False


def _summary(
    ctype: ConnectorType, instance: ConnectorInstance | None, stale: bool, credentialed: bool = True
) -> ConnectorSummary:
    state = instance.state if instance else "not_configured"
    if not credentialed and state not in INACTIVE:
        # No credential behind it: nothing was ever read, so there is no sync to report either.
        return ConnectorSummary(
            key=ctype.key, name=ctype.name, category=ctype.category, state="not_configured",
            state_label="No credential stored", last_successful_sync=None, sync_label="—",
            instances=0, stale=False,
        )
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


async def _shared(session: AsyncSession, key: str) -> Shared | None:
    shared_key = SHARED_CREDENTIALS.get(key)
    if not shared_key:
        return None
    return await session.get(ConnectorType, shared_key), await _instance_for(session, shared_key)


async def _detail(session: AsyncSession, ctype: ConnectorType) -> ConnectorDetail:
    instance = await _instance_for(session, ctype.key)
    freshness = await resolve(session, [ctype.key])
    credentialed = await _has_credential(ctype, instance, await _shared(session, ctype.key))
    stale = _is_active(instance) and freshness.stale
    summary = _summary(ctype, instance, stale=stale, credentialed=credentialed)

    fields = []
    refs = (instance.secret_refs or {}) if instance else {}
    for field in ctype.fields:
        is_secret = field["type"] == "secret"
        if is_secret:
            # Write-only: a secret comes back as a placeholder, never as a value - and the
            # placeholder only claims a value is stored when one resolves in the vault.
            ref = refs.get(field["key"])
            if not ref:
                placeholder = NOT_STORED
            elif await vault.read(ref):
                placeholder = VAULT_PLACEHOLDER
            elif await vault.stored(ref):
                # A value is there but this machine's key can't open it. A seeded reference with
                # nothing behind it is a different thing, and says "Not set" as it always did.
                placeholder = FROM_ANOTHER_MACHINE
            else:
                placeholder = NOT_STORED
        else:
            # The catalog's example is a hint, not a value: nothing reads a value that was only
            # ever shown, so showing it as one would look configured and be empty.
            placeholder = field.get("seed_value") or ""
        fields.append(
            ConnectorField(
                key=field["key"],
                label=field["label"],
                help=field["help"],
                type=field["type"],
                value=None if is_secret else (instance.config.get(field["key"]) if instance else None),
                placeholder=placeholder,
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
    by_key = {t.key: t for t in types}
    out = []
    for ctype in types:
        instance = instances.get(ctype.key)
        shared_key = SHARED_CREDENTIALS.get(ctype.key)
        shared = (by_key.get(shared_key), instances.get(shared_key)) if shared_key else None
        out.append(_summary(
            ctype, instance, stale=_is_active(instance) and ctype.key in stale_keys,
            credentialed=await _has_credential(ctype, instance, shared),
        ))
    return out


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
    ref = f"vault://shiftleft/{connector_key}/{body.field_key}"
    # The value is encrypted into the vault table (app/services/vault.py); only the reference
    # is kept here, so a connector resolves it back only at the moment it actually calls out.
    await vault.write(ref, body.value)
    instance.secret_refs = {**(instance.secret_refs or {}), body.field_key: ref}
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
    config = dict(instance.config) if instance else {}
    secret_refs = dict(instance.secret_refs) if instance else {}
    if shared_key := SHARED_CREDENTIALS.get(connector_key):
        # This connector declares "Shares the X connection" and has no credential of its own -
        # its own fields (if any) still win on a name clash.
        shared = await _instance_for(session, shared_key)
        if shared:
            config = {**shared.config, **config}
            secret_refs = {**shared.secret_refs, **secret_refs}
    connector = get_connector(ctype.key, ctype.name, config, secret_refs)
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
