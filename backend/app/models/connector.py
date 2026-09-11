from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

CONNECTOR_STATES = ("connected", "stale", "disabled", "not_configured", "error")


class ConnectorType(Base, TimestampMixin):
    """Declares one connector's own auth model and field set.

    The config form is data-driven from this row - there is no single shared connector form.
    """

    __tablename__ = "connector_types"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    # [{"label": ..., "recommended": bool}]
    auth_methods: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # [{"key","label","help","type": "text|secret|list","placeholder"}]
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    scopes: Mapped[str] = mapped_column(Text, default="")
    rate_limits: Mapped[str] = mapped_column(Text, default="")
    staleness_minutes: Mapped[int] = mapped_column(Integer, default=30)
    # Connectors that never store source content, only presence and status (TDD s5).
    status_only: Mapped[bool] = mapped_column(Boolean, default=False)

    instances: Mapped[list["ConnectorInstance"]] = relationship(
        back_populates="connector_type", cascade="all, delete-orphan"
    )


class ConnectorInstance(Base, TimestampMixin):
    """One configured connection. Secrets are vault references - the value never lands here."""

    __tablename__ = "connector_instances"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    connector_key: Mapped[str] = mapped_column(
        ForeignKey("connector_types.key", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    label: Mapped[str] = mapped_column(String(160), default="")
    state: Mapped[str] = mapped_column(String(32), default="not_configured")
    auth_method: Mapped[str | None] = mapped_column(String(160), default=None)
    # Non-secret field values only. Secret fields carry a vault reference, never a value.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secret_refs: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    last_successful_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    connector_type: Mapped[ConnectorType] = relationship(back_populates="instances")
