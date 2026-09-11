"""The shift-left rollout: how far a project has moved from observing evidence to gating on it.

See docs/PROPOSAL-ShiftLeft-Pivot.md s9-s10. The stage is a recorded decision, not a status -
whether a project may leave its stage is computed from the rows below on every read, never stored.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# The four stages of the gating path, in order. Index is the stored stage.
STAGES = ("observe", "warn", "soft_gate", "hard_gate")

# What a surface is doing. Gating surfaces warn or block; the rest are simply live or not.
SURFACE_MODES = ("off", "live", "warn", "block")


class RolloutState(Base, TimestampMixin):
    """One row per enrolled project. A project with no row is not enrolled - a gap, not a pass."""

    __tablename__ = "rollout_states"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    stage: Mapped[int] = mapped_column(Integer, default=0)
    stage_since: Mapped[date] = mapped_column(Date())
    # The evidence policy is versioned in git; every evaluation names the version it ran.
    policy_version: Mapped[str] = mapped_column(String(64))
    policy_ref: Mapped[str] = mapped_column(String(200), default="")
    # Leaving Warn needs the team to agree the reasons are fair. A named person records it.
    team_signoff_by: Mapped[str | None] = mapped_column(String(160), default=None)
    team_signoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Leaving Soft gate needs the waivers reviewed with the ETLs.
    waiver_review_on: Mapped[date | None] = mapped_column(Date(), default=None)


class RolloutSurface(Base, TimestampMixin):
    """A place the evidence engine shows up where people already work."""

    __tablename__ = "rollout_surfaces"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_rollout_surface"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(160))
    # The connector the surface runs through - its freshness is the surface's freshness.
    connector_key: Mapped[str] = mapped_column(String(64))
    # True for surfaces that can stop work (validator, PR check); false for the ones that inform.
    gating: Mapped[bool] = mapped_column(Boolean, default=False)
    # The first stage at which the surface is expected to be switched on.
    from_stage: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(16), default="off")
    coverage_done: Mapped[int] = mapped_column(Integer, default=0)
    coverage_total: Mapped[int] = mapped_column(Integer, default=0)
    coverage_unit: Mapped[str] = mapped_column(String(64), default="")
    gap_note: Mapped[str] = mapped_column(Text, default="")
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # A digest runs weekly; a PR check fires many times a day. Silence is judged per surface.
    expected_every_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    events_14d: Mapped[int] = mapped_column(Integer, default=0)
    events_unit: Mapped[str] = mapped_column(String(64), default="events")
    source_ref: Mapped[str] = mapped_column(String(200), default="")


class DetectionAudit(Base, TimestampMixin):
    """Detected state against a manual audit, per artifact, for the latest audited sprint.

    This is the spike's headline measurement: how often evidence is found without anyone
    tagging it by hand.
    """

    __tablename__ = "detection_audits"
    __table_args__ = (UniqueConstraint("project_id", "artifact_key", name="uq_detection_audit"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    artifact_key: Mapped[str] = mapped_column(
        ForeignKey("artifact_definitions.key", ondelete="CASCADE")
    )
    # The system the detector reads - its freshness is the detector's freshness.
    source_connector: Mapped[str] = mapped_column(String(64), default="jira")
    audited: Mapped[int] = mapped_column(Integer)
    # Shown as missing, but the audit found it. This is what makes a warning unfair.
    false_missing: Mapped[int] = mapped_column(Integer, default=0)
    # Shown as present, but the audit found nothing usable. This is what lets a gap through.
    false_present: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(Text, default="")
    audited_on: Mapped[date] = mapped_column(Date())
    auditor: Mapped[str] = mapped_column(String(160))
    features: Mapped[str] = mapped_column(Text, default="")


class RolloutSprint(Base, TimestampMixin):
    """One sprint of rollout history. Warning outcomes are None before the project reached Warn."""

    __tablename__ = "rollout_sprints"
    __table_args__ = (UniqueConstraint("project_id", "ends", name="uq_rollout_sprint"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ends: Mapped[date] = mapped_column(Date())
    accuracy: Mapped[float | None] = mapped_column(Float, default=None)
    warnings: Mapped[int | None] = mapped_column(Integer, default=None)
    evidence_added: Mapped[int | None] = mapped_column(Integer, default=None)
    waived: Mapped[int | None] = mapped_column(Integer, default=None)
    ignored: Mapped[int | None] = mapped_column(Integer, default=None)
    # Disputed and confirmed wrong: the evidence was there and the engine missed it.
    false_red: Mapped[int | None] = mapped_column(Integer, default=None)
