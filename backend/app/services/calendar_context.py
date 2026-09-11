"""Where "today" and "how much data exists" come from.

Both are resolved once, here, so a period never depends on wall-clock time in one place and on
the data in another. `data_through` is the last day any snapshot covers: a period in progress is
only ever as long as the data behind it, which is what keeps a partial quarter from reading as a
throughput collapse.
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metrics import MetricsSnapshot
from app.services.delivery_facts import KIND


def today() -> date:
    return datetime.now(timezone.utc).date()


async def data_through(session: AsyncSession, project_id: str | None = None) -> date:
    query = select(func.max(MetricsSnapshot.computed_at)).where(MetricsSnapshot.kind == KIND)
    if project_id:
        query = query.where(MetricsSnapshot.project_id == project_id)
    latest = (await session.execute(query)).scalar_one_or_none()
    if latest is None:
        return today()
    return min(latest.date(), today())


async def stored_period_keys(session: AsyncSession, project_id: str) -> set[str]:
    rows = (
        await session.execute(
            select(MetricsSnapshot.period).where(
                MetricsSnapshot.project_id == project_id, MetricsSnapshot.kind == KIND
            )
        )
    ).scalars().all()
    return set(rows)
