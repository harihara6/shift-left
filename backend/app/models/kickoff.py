from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# context -> planned -> applying -> applied, or partial when some items failed (a retry applies the
# same frozen plan again). Everything from "applying" on has been confirmed by a named person, and
# the plan is frozen: a second kickoff is a new session, so a confirmed plan stays a record of
# exactly what was confirmed.
KICKOFF_STATES = ("context", "planned", "applying", "partial", "applied")


class KickoffSession(Base, TimestampMixin):
    """One PRD taken through Feature Kickoff: what it said, what was chosen, what was confirmed.

    `data` holds what was *read or decided*: facts, choices, findings, suggestion decisions,
    excluded items, and once applied the frozen plan and its results. Rule outcomes and the live
    plan are computed from it on every read, never stored, so no outcome exists that nobody can
    trace back to a fact.
    """

    __tablename__ = "kickoff_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    # The PRD is read with the actor's own Confluence permissions, so the session is theirs.
    actor: Mapped[str] = mapped_column(String(160), index=True)
    page_id: Mapped[str] = mapped_column(String(64))
    page_title: Mapped[str] = mapped_column(String(300))
    page_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="context")
    # Which provider and model read the PRD, and whether it fell back to the keyword reader.
    # Recorded because how a draft was produced is part of reading it (product rule 6).
    provider: Mapped[str] = mapped_column(String(32), default="rules")
    model: Mapped[str] = mapped_column(String(120), default="rules")
    reader: Mapped[str] = mapped_column(String(16), default="rules")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(160), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    note: Mapped[str] = mapped_column(Text, default="")
