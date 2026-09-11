"""Freshness resolution.

One rule, applied in one place: a source past its staleness threshold, or with no successful sync
at all, can never contribute to a green state. Missing is not green, and stale-but-green is worse
than visibly broken.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.connector import ConnectorInstance, ConnectorType
from app.schemas.common import ConnectorFreshness, Freshness, RagState

# Any state at or above this rank is "green enough to be downgraded" when a source is stale.
_DOWNGRADE = {"good": "watch"}


def age_minutes(moment: datetime | None, now: datetime | None = None) -> int | None:
    """Whole minutes since `moment`. Naive timestamps are UTC - SQLite drops the offset."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(((now or datetime.now(timezone.utc)) - moment).total_seconds() // 60)


def humanize_age(minutes: int | None) -> str:
    if minutes is None:
        return "never"
    if minutes < 1:
        return "live"
    if minutes < 60:
        return f"{minutes}m ago"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins:02d}m ago" if mins else f"{hours}h ago"
    days, hours = divmod(hours, 24)
    return f"{days}d ago"


async def resolve(session: AsyncSession, connector_keys: list[str]) -> Freshness:
    """Build the freshness block for the connectors a widget or page depends on."""
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(ConnectorType, ConnectorInstance)
            .join(ConnectorInstance, ConnectorInstance.connector_key == ConnectorType.key, isouter=True)
            .where(ConnectorType.key.in_(connector_keys))
        )
    ).all()

    by_key: dict[str, ConnectorFreshness] = {}
    for ctype, instance in rows:
        last = instance.last_successful_sync if instance else None
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = age_minutes(last, now)
        stale = age is None or age > ctype.staleness_minutes
        entry = ConnectorFreshness(
            key=ctype.key,
            name=ctype.name,
            state=instance.state if instance else "not_configured",
            last_successful_sync=last,
            age_minutes=age,
            threshold_minutes=ctype.staleness_minutes,
            stale=stale,
            missing=last is None,
        )
        # Keep the freshest instance per connector type.
        seen = by_key.get(ctype.key)
        if seen is None or (age is not None and (seen.age_minutes is None or age < seen.age_minutes)):
            by_key[ctype.key] = entry

    # A connector the page depends on but that has no row at all is a gap, not an omission.
    default_threshold = get_settings().default_staleness_minutes
    for key in connector_keys:
        by_key.setdefault(
            key,
            ConnectorFreshness(
                key=key, name=key, state="not_configured", threshold_minutes=default_threshold,
                stale=True, missing=True,
            ),
        )

    connectors = sorted(by_key.values(), key=lambda c: c.name)
    stale_ones = [c for c in connectors if c.stale]
    oldest = min((c.last_successful_sync for c in connectors if c.last_successful_sync), default=None)
    note = ""
    if stale_ones:
        names = ", ".join(c.name for c in stale_ones)
        note = f"{names} past the freshness threshold — nothing on this page renders green until it syncs."
    return Freshness(stale=bool(stale_ones), oldest_sync=oldest, note=note, connectors=connectors)


def restrict(freshness: Freshness, connector_keys: list[str] | set[str]) -> Freshness:
    """The slice of a page's freshness that one widget actually depends on.

    A PR check reads GitHub; it should not be held out of green because Xray is stale.
    """
    connectors = [c for c in freshness.connectors if c.key in connector_keys]
    stale_ones = [c for c in connectors if c.stale]
    note = ""
    if stale_ones:
        names = ", ".join(c.name for c in stale_ones)
        note = f"{names} past the freshness threshold — nothing here renders green until it syncs."
    return Freshness(
        stale=bool(stale_ones),
        oldest_sync=min((c.last_successful_sync for c in connectors if c.last_successful_sync), default=None),
        note=note,
        connectors=connectors,
    )


def guard(state: RagState, freshness: Freshness) -> RagState:
    """Downgrade a green state when the data behind it is stale, and say why."""
    if not freshness.stale or state.rag not in _DOWNGRADE:
        return state
    stale_names = ", ".join(c.name for c in freshness.connectors if c.stale)
    return RagState.of(
        _DOWNGRADE[state.rag],
        [*state.reasons, f"Held out of green: {stale_names} has not synced within its threshold."],
    )
