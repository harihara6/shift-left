from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.template import ProjectTemplate

# Project-scoped roles (TDD s5). No global role bypasses project scope except platform-admin,
# which is held outside this table.
ROLES = ("viewer", "contributor", "admin")
GRANT_SOURCES = ("SSO group", "Explicit grant")


class Project(Base, TimestampMixin):
    """A project is the unit of access, ownership and connector scope."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    owner: Mapped[str] = mapped_column(String(160))
    created_on: Mapped[date] = mapped_column(Date())
    # Which repositories the PR metrics cover. Stated on the widget, because a PR count is
    # meaningless without knowing which repos were in scope.
    pr_scope: Mapped[str] = mapped_column(String(400), default="")
    # Soft delete (TDD s9) - archiving keeps the audit trail intact.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    access: Mapped[list["ProjectAccess"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="ProjectAccess.principal", lazy="selectin"
    )
    templates: Mapped[list["ProjectTemplate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )


class ProjectAccess(Base, TimestampMixin):
    """user or SSO-group -> project -> role. Evaluated at the API layer on every read and write."""

    __tablename__ = "project_access"
    __table_args__ = (UniqueConstraint("project_id", "principal", name="uq_access_principal"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    principal: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    via: Mapped[str] = mapped_column(String(32))
    granted_by: Mapped[str] = mapped_column(String(160), default="system")

    project: Mapped[Project] = relationship(back_populates="access")
