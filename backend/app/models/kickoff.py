from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
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
    # The drafted technical design and where it was published, when step 7 asked for one.
    tdd: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # How many times the analysis has run. Each run replaces the live plan; the run it replaced is
    # kept in `kickoff_runs`, so nobody loses a draft (or their edits to it) by running again.
    runs: Mapped[int] = mapped_column(Integer, default=0)
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class KickoffRun(Base, TimestampMixin):
    """One drafting of a plan, kept whole.

    The live plan on the analysis is the one people edit and create tickets from. Every draft is
    also recorded here, so an earlier run can be read back and two runs compared - which is the
    point of running again while the requirement is still moving.
    """

    __tablename__ = "kickoff_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("kickoff_analyses.id", ondelete="CASCADE"), index=True
    )
    run_number: Mapped[int] = mapped_column(Integer)
    # run: drafted from the inputs. refine: amended the plan that was already there.
    kind: Mapped[str] = mapped_column(String(16), default="run")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    reader: Mapped[str] = mapped_column(String(32), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    # What the person asked for on top of the standing instruction, as they typed it.
    instructions: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tdd: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # The fingerprint of the inputs this run was drafted from.
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(160))


class KickoffSettings(Base, TimestampMixin):
    """Service-wide Feature Kickoff defaults: one row, id 1.

    These are starting values a new analysis is filled in with, never a lock: every one of them
    stays editable on the analysis itself. No credential lives here - those stay in Connectors and
    the vault - so any signed-in user may read this; only a platform admin may change it.
    """

    __tablename__ = "kickoff_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    # The TDD that shows the house style, and where a generated one is written.
    tdd_template_url: Mapped[str] = mapped_column(Text, default="")
    tdd_space_key: Mapped[str] = mapped_column(String(64), default="")
    tdd_parent_url: Mapped[str] = mapped_column(Text, default="")
    # Section keys ticked by default. [] means nothing is pre-ticked.
    tdd_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    # The backlog a new analysis points at, and what its tickets carry.
    jira_project_url: Mapped[str] = mapped_column(Text, default="")
    jira_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Standing instructions prefilled into every run, on top of the prompt itself.
    analysis_prompt: Mapped[str] = mapped_column(Text, default="")
    tdd_prompt: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(String(160), default="")
