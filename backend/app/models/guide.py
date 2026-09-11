from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WidgetGuide(Base, TimestampMixin):
    """The four fixed questions, stored beside the widget definition rather than in a doc.

    A rendered widget with no guide row fails the startup check in app.services.guides - which is
    the point: a new widget cannot ship without saying what decision it supports, where it comes
    from, how it is fetched and how to tag it at source.
    """

    __tablename__ = "widget_guides"
    __table_args__ = (UniqueConstraint("perspective", "widget_key", name="uq_guide_widget"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    perspective: Mapped[str] = mapped_column(String(32), index=True)
    widget_key: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)
    widget: Mapped[str] = mapped_column(String(200))
    decision: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    fetch: Mapped[str] = mapped_column(Text)
    tagging: Mapped[str] = mapped_column(Text)


class PerspectiveGuide(Base, TimestampMixin):
    """Page-level framing. It exists only to group the per-widget entries."""

    __tablename__ = "perspective_guides"

    perspective: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(Text)
    # Audience described as situations, not role titles.
    audience: Mapped[str] = mapped_column(Text, default="[]")
