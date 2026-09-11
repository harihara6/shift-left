from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# The six PRD-aligned perspectives. One template per perspective - never eight.
PERSPECTIVES = {
    "discipline": "Evidence of record",
    "execution": "Execution health",
    "delivery": "Delivery control",
    "release": "Release confidence",
    "portfolio": "Portfolio quality",
    "signal": "Executive signal",
}


class Template(Base, TimestampMixin):
    """A catalog template. Opinionated starting point, never live-bound to a project."""

    __tablename__ = "templates"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    perspective: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    audience: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(Text, default="")
    freshness_expectation: Mapped[str] = mapped_column(String(120), default="")
    known_limitations: Mapped[str] = mapped_column(Text, default="")

    widgets: Mapped[list["TemplateWidget"]] = relationship(
        back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateWidget.position", lazy="selectin"
    )


class TemplateWidget(Base, TimestampMixin):
    __tablename__ = "template_widgets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(ForeignKey("templates.key", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    connector_key: Mapped[str] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(Text)
    refresh_interval: Mapped[str] = mapped_column(String(32))
    drill_template: Mapped[str] = mapped_column(Text, default="")
    # Points at the widget_guides row that answers the four fixed questions for this widget.
    guide_key: Mapped[str | None] = mapped_column(String(64), default=None)

    template: Mapped[Template] = relationship(back_populates="widgets")


class ProjectTemplate(Base, TimestampMixin):
    """A template enabled on a project. Deep copy - later template edits never reach this row."""

    __tablename__ = "project_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    template_key: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    perspective: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Origin metadata is retained for traceability only, never for sync.
    copied_from_version: Mapped[int] = mapped_column(Integer, default=1)
    copied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    project = relationship("Project", back_populates="templates")
    widgets: Mapped[list["WidgetBinding"]] = relationship(
        back_populates="project_template", cascade="all, delete-orphan",
        order_by="WidgetBinding.position", lazy="selectin"
    )


class WidgetBinding(Base, TimestampMixin):
    """A widget's connector + query binding inside one project. Independently editable after copy."""

    __tablename__ = "widget_bindings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_template_id: Mapped[int] = mapped_column(
        ForeignKey("project_templates.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    connector_key: Mapped[str] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(Text)
    refresh_interval: Mapped[str] = mapped_column(String(32))
    drill_template: Mapped[str] = mapped_column(Text, default="")
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    guide_key: Mapped[str | None] = mapped_column(String(64), default=None)

    project_template: Mapped[ProjectTemplate] = relationship(back_populates="widgets")
