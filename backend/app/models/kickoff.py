from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# draft -> analysed -> created (partial while some tickets failed to create). Inputs stay editable
# in every state: a saved analysis is reopened, changed and run again, and the plan says when it
# was drafted from inputs that have since changed.
ANALYSIS_STATES = ("draft", "analysed", "created", "partial")


class KickoffAnalysis(Base, TimestampMixin):
    """One feature taken from a PRD to an ordered backlog: the seven steps' inputs and results.

    `inputs` holds what was read or chosen, one key per step: the PRD as read, the repos to code
    in, the repos relied on, the approved compliance, API docs and third-party providers, and the
    backlog link. `plan` is the drafted analysis, kept with the fingerprint of the inputs it was
    drafted from; `backlog` records what was created in Jira, per task, and by whom.
    """

    __tablename__ = "kickoff_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="Untitled analysis")
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_by: Mapped[str] = mapped_column(String(160))
    updated_by: Mapped[str] = mapped_column(String(160))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    backlog: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # How many times the analysis has run: each run replaces the plan, and the count says so.
    runs: Mapped[int] = mapped_column(Integer, default=0)
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
