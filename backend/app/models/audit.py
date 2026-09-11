from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Access-grant changes are a distinct, higher-sensitivity audit category with longer
# retention than ordinary dashboard CRUD (TDD s11).
SENSITIVE_CATEGORIES = ("access", "credential")


class AuditLog(Base, TimestampMixin):
    """Append-only. Never updated, never deleted by application code."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(200), index=True)
    action: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32), default="dashboard", index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, default=365)
    note: Mapped[str] = mapped_column(Text, default="")
