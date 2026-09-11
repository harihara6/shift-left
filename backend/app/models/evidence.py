from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# The five states an artifact can be in. "waived" leaves the denominator; it never counts as a pass.
ARTIFACT_STATES = ("present", "drafted", "stale", "missing", "waived")

# Which gate an artifact is due at. "Both" is due at Ready and again at Done.
GATES = ("Ready", "Done", "Both")

# Risk tier drives what may be scoped out at all - a new capability may scope out nothing.
TIERS = ("New capability", "Major change", "Minor change", "Config / copy")

ACTION_STATES = ("open", "acknowledged", "resolved")


class ArtifactDefinition(Base, TimestampMixin):
    """One of the eleven canonical artifacts. Order is the checklist order and is meaningful."""

    __tablename__ = "artifact_definitions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    accountable: Mapped[str] = mapped_column(String(200))
    gate: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(200))
    # Threat models and security findings are presence + status only; content stays at source.
    status_only: Mapped[bool] = mapped_column(Boolean, default=False)


class FeatureEvidence(Base, TimestampMixin):
    """A tracked feature and the AI draft attached to it.

    The draft counts toward nothing until `ai_accepted_by` names a person - that column is the
    whole mechanism behind "AI drafts, humans accept".
    """

    __tablename__ = "feature_evidence"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_feature_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(32), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    tier: Mapped[str] = mapped_column(String(32))
    gate: Mapped[str] = mapped_column(String(16))
    release: Mapped[str] = mapped_column(String(32), default="2026.3", index=True)
    owner: Mapped[str] = mapped_column(String(160))
    next_action: Mapped[str] = mapped_column(Text, default="")
    action_age: Mapped[str] = mapped_column(String(32), default="")

    ai_draft: Mapped[str] = mapped_column(Text, default="")
    ai_drawn_from: Mapped[str] = mapped_column(Text, default="")
    ai_accepted_by: Mapped[str | None] = mapped_column(String(160), default=None)
    ai_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    artifacts: Mapped[list["NormalizedArtifact"]] = relationship(
        back_populates="feature", cascade="all, delete-orphan",
        order_by="NormalizedArtifact.position", lazy="selectin",
    )


class NormalizedArtifact(Base, TimestampMixin):
    """One artifact's state for one feature, as normalized from its source system."""

    __tablename__ = "normalized_artifacts"
    __table_args__ = (UniqueConstraint("feature_id", "artifact_key", name="uq_feature_artifact"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("feature_evidence.id", ondelete="CASCADE"), index=True
    )
    artifact_key: Mapped[str] = mapped_column(
        ForeignKey("artifact_definitions.key", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    # The record in the source system this state was read from, if there is one.
    source_ref: Mapped[str | None] = mapped_column(String(200), default=None)
    source_connector: Mapped[str] = mapped_column(String(64), default="jira")

    feature: Mapped[FeatureEvidence] = relationship(back_populates="artifacts")


class ArtifactWaiver(Base, TimestampMixin):
    """A scoped-out artifact. Reportable by design: it leaves the denominator, not the record."""

    __tablename__ = "artifact_waivers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    feature_key: Mapped[str] = mapped_column(String(32), index=True)
    artifact: Mapped[str] = mapped_column(String(200))
    tier: Mapped[str] = mapped_column(String(32))
    owner: Mapped[str] = mapped_column(String(160))
    waived_at: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text)


class ActionRecord(Base, TimestampMixin):
    """Auto-created when a signal goes red. Acknowledgement records who, and when."""

    __tablename__ = "action_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    signal: Mapped[str] = mapped_column(String(200))
    next_action: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(160))
    age: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    severity: Mapped[str] = mapped_column(String(16), default="poor")
    acknowledged_by: Mapped[str | None] = mapped_column(String(160), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
