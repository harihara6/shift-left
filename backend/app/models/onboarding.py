from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# draft -> accepted is the only transition that creates anything. A draft that is never
# accepted stays a draft: it is a record of what was proposed, not of what was set up.
ONBOARDING_STATES = ("draft", "accepted")


class OnboardingSession(Base, TimestampMixin):
    """One guided setup attempt: what was searched for, what was found, and who accepted it.

    The draft is kept verbatim even after acceptance, so "why is this project bound to that
    Jira key" has an answer that names the evidence and the person (PRD s9, product rule 6).
    """

    __tablename__ = "onboarding_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Discovery reads with the caller's own permissions, so a draft belongs to its actor and
    # is not readable by anyone else.
    actor: Mapped[str] = mapped_column(String(160), index=True)
    hint: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    # Which resolver produced it: "claude" or "name-match". Kept because how a proposal was
    # arrived at is part of reading it.
    mode: Mapped[str] = mapped_column(String(32), default="name-match")
    draft: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    accepted_by: Mapped[str | None] = mapped_column(String(160), default=None)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str] = mapped_column(Text, default="")
