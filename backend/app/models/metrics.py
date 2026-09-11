from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MetricsSnapshot(Base, TimestampMixin):
    """A precomputed aggregate for one project, period and metric kind.

    Payload is the normalized, render-ready shape the widget reads. Source connector keys are
    recorded so freshness can be resolved without the widget guessing where its data came from.
    """

    __tablename__ = "metrics_snapshots"
    __table_args__ = (UniqueConstraint("project_id", "kind", "period", name="uq_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    period: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_connector_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
