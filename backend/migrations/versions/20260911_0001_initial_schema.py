"""Initial schema: every table in TDD s9 that the service has built so far.

Revision ID: 0001
Revises:
Create Date: 2026-09-11 07:30:52.224171
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_definitions",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("accountable", sa.String(length=200), nullable=False),
        sa.Column("gate", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("status_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=160), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_actor"), "audit_logs", ["actor"], unique=False)
    op.create_index(op.f("ix_audit_logs_category"), "audit_logs", ["category"], unique=False)
    op.create_index(op.f("ix_audit_logs_project_id"), "audit_logs", ["project_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_resource_id"), "audit_logs", ["resource_id"], unique=False)
    op.create_table(
        "connector_types",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("auth_methods", sa.JSON(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("rate_limits", sa.Text(), nullable=False),
        sa.Column("staleness_minutes", sa.Integer(), nullable=False),
        sa.Column("status_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "perspective_guides",
        sa.Column("perspective", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("perspective"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("created_on", sa.Date(), nullable=False),
        sa.Column("pr_scope", sa.String(length=400), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_key"), "projects", ["key"], unique=True)
    op.create_table(
        "templates",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("perspective", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("freshness_expectation", sa.String(length=120), nullable=False),
        sa.Column("known_limitations", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "widget_guides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("perspective", sa.String(length=32), nullable=False),
        sa.Column("widget_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("widget", sa.String(length=200), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("fetch", sa.Text(), nullable=False),
        sa.Column("tagging", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("perspective", "widget_key", name="uq_guide_widget"),
    )
    op.create_index(op.f("ix_widget_guides_perspective"), "widget_guides", ["perspective"], unique=False)
    op.create_table(
        "action_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("signal", sa.String(length=200), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("age", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=160), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_action_records_project_id"), "action_records", ["project_id"], unique=False)
    op.create_table(
        "artifact_waivers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("feature_key", sa.String(length=32), nullable=False),
        sa.Column("artifact", sa.String(length=200), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("waived_at", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_artifact_waivers_feature_key"), "artifact_waivers", ["feature_key"], unique=False
    )
    op.create_index(op.f("ix_artifact_waivers_project_id"), "artifact_waivers", ["project_id"], unique=False)
    op.create_table(
        "connector_instances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("auth_method", sa.String(length=160), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("secret_refs", sa.JSON(), nullable=False),
        sa.Column("last_successful_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["connector_key"], ["connector_types.key"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_connector_instances_connector_key"), "connector_instances", ["connector_key"], unique=False
    )
    op.create_index(
        op.f("ix_connector_instances_project_id"), "connector_instances", ["project_id"], unique=False
    )
    op.create_table(
        "detection_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_key", sa.String(length=64), nullable=False),
        sa.Column("source_connector", sa.String(length=64), nullable=False),
        sa.Column("audited", sa.Integer(), nullable=False),
        sa.Column("false_missing", sa.Integer(), nullable=False),
        sa.Column("false_present", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("audited_on", sa.Date(), nullable=False),
        sa.Column("auditor", sa.String(length=160), nullable=False),
        sa.Column("features", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_key"], ["artifact_definitions.key"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "artifact_key", name="uq_detection_audit"),
    )
    op.create_index(op.f("ix_detection_audits_project_id"), "detection_audits", ["project_id"], unique=False)
    op.create_table(
        "feature_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tier", sa.String(length=32), nullable=False),
        sa.Column("gate", sa.String(length=16), nullable=False),
        sa.Column("release", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("action_age", sa.String(length=32), nullable=False),
        sa.Column("ai_draft", sa.Text(), nullable=False),
        sa.Column("ai_drawn_from", sa.Text(), nullable=False),
        sa.Column("ai_accepted_by", sa.String(length=160), nullable=True),
        sa.Column("ai_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_feature_key"),
    )
    op.create_index(op.f("ix_feature_evidence_key"), "feature_evidence", ["key"], unique=False)
    op.create_index(op.f("ix_feature_evidence_project_id"), "feature_evidence", ["project_id"], unique=False)
    op.create_index(op.f("ix_feature_evidence_release"), "feature_evidence", ["release"], unique=False)
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_connector_keys", sa.JSON(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "kind", "period", name="uq_snapshot"),
    )
    op.create_index(op.f("ix_metrics_snapshots_kind"), "metrics_snapshots", ["kind"], unique=False)
    op.create_index(op.f("ix_metrics_snapshots_period"), "metrics_snapshots", ["period"], unique=False)
    op.create_index(
        op.f("ix_metrics_snapshots_project_id"), "metrics_snapshots", ["project_id"], unique=False
    )
    op.create_table(
        "onboarding_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False),
        sa.Column("hint", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("accepted_by", sa.String(length=160), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_onboarding_sessions_actor"), "onboarding_sessions", ["actor"], unique=False)
    op.create_table(
        "project_access",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("principal", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("via", sa.String(length=32), nullable=False),
        sa.Column("granted_by", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "principal", name="uq_access_principal"),
    )
    op.create_index(op.f("ix_project_access_project_id"), "project_access", ["project_id"], unique=False)
    op.create_table(
        "project_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("template_key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("perspective", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("copied_from_version", sa.Integer(), nullable=False),
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_project_templates_project_id"), "project_templates", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_project_templates_template_key"), "project_templates", ["template_key"], unique=False
    )
    op.create_table(
        "rollout_sprints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("ends", sa.Date(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("warnings", sa.Integer(), nullable=True),
        sa.Column("evidence_added", sa.Integer(), nullable=True),
        sa.Column("waived", sa.Integer(), nullable=True),
        sa.Column("ignored", sa.Integer(), nullable=True),
        sa.Column("false_red", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "ends", name="uq_rollout_sprint"),
    )
    op.create_index(op.f("ix_rollout_sprints_project_id"), "rollout_sprints", ["project_id"], unique=False)
    op.create_table(
        "rollout_states",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("stage_since", sa.Date(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_ref", sa.String(length=200), nullable=False),
        sa.Column("team_signoff_by", sa.String(length=160), nullable=True),
        sa.Column("team_signoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiver_review_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "rollout_surfaces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("gating", sa.Boolean(), nullable=False),
        sa.Column("from_stage", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("coverage_done", sa.Integer(), nullable=False),
        sa.Column("coverage_total", sa.Integer(), nullable=False),
        sa.Column("coverage_unit", sa.String(length=64), nullable=False),
        sa.Column("gap_note", sa.Text(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_every_minutes", sa.Integer(), nullable=False),
        sa.Column("events_14d", sa.Integer(), nullable=False),
        sa.Column("events_unit", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_rollout_surface"),
    )
    op.create_index(op.f("ix_rollout_surfaces_project_id"), "rollout_surfaces", ["project_id"], unique=False)
    op.create_table(
        "template_widgets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_key", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("refresh_interval", sa.String(length=32), nullable=False),
        sa.Column("drill_template", sa.Text(), nullable=False),
        sa.Column("guide_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_key"], ["templates.key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_template_widgets_template_key"), "template_widgets", ["template_key"], unique=False
    )
    op.create_table(
        "normalized_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("feature_id", sa.Integer(), nullable=False),
        sa.Column("artifact_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=200), nullable=True),
        sa.Column("source_connector", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["artifact_key"], ["artifact_definitions.key"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feature_id"], ["feature_evidence.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feature_id", "artifact_key", name="uq_feature_artifact"),
    )
    op.create_index(
        op.f("ix_normalized_artifacts_feature_id"), "normalized_artifacts", ["feature_id"], unique=False
    )
    op.create_table(
        "widget_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_template_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("refresh_interval", sa.String(length=32), nullable=False),
        sa.Column("drill_template", sa.Text(), nullable=False),
        sa.Column("last_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guide_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_template_id"], ["project_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_widget_bindings_project_template_id"),
        "widget_bindings",
        ["project_template_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_widget_bindings_project_template_id"), table_name="widget_bindings")
    op.drop_table("widget_bindings")
    op.drop_index(op.f("ix_normalized_artifacts_feature_id"), table_name="normalized_artifacts")
    op.drop_table("normalized_artifacts")
    op.drop_index(op.f("ix_template_widgets_template_key"), table_name="template_widgets")
    op.drop_table("template_widgets")
    op.drop_index(op.f("ix_rollout_surfaces_project_id"), table_name="rollout_surfaces")
    op.drop_table("rollout_surfaces")
    op.drop_table("rollout_states")
    op.drop_index(op.f("ix_rollout_sprints_project_id"), table_name="rollout_sprints")
    op.drop_table("rollout_sprints")
    op.drop_index(op.f("ix_project_templates_template_key"), table_name="project_templates")
    op.drop_index(op.f("ix_project_templates_project_id"), table_name="project_templates")
    op.drop_table("project_templates")
    op.drop_index(op.f("ix_project_access_project_id"), table_name="project_access")
    op.drop_table("project_access")
    op.drop_index(op.f("ix_onboarding_sessions_actor"), table_name="onboarding_sessions")
    op.drop_table("onboarding_sessions")
    op.drop_index(op.f("ix_metrics_snapshots_project_id"), table_name="metrics_snapshots")
    op.drop_index(op.f("ix_metrics_snapshots_period"), table_name="metrics_snapshots")
    op.drop_index(op.f("ix_metrics_snapshots_kind"), table_name="metrics_snapshots")
    op.drop_table("metrics_snapshots")
    op.drop_index(op.f("ix_feature_evidence_release"), table_name="feature_evidence")
    op.drop_index(op.f("ix_feature_evidence_project_id"), table_name="feature_evidence")
    op.drop_index(op.f("ix_feature_evidence_key"), table_name="feature_evidence")
    op.drop_table("feature_evidence")
    op.drop_index(op.f("ix_detection_audits_project_id"), table_name="detection_audits")
    op.drop_table("detection_audits")
    op.drop_index(op.f("ix_connector_instances_project_id"), table_name="connector_instances")
    op.drop_index(op.f("ix_connector_instances_connector_key"), table_name="connector_instances")
    op.drop_table("connector_instances")
    op.drop_index(op.f("ix_artifact_waivers_project_id"), table_name="artifact_waivers")
    op.drop_index(op.f("ix_artifact_waivers_feature_key"), table_name="artifact_waivers")
    op.drop_table("artifact_waivers")
    op.drop_index(op.f("ix_action_records_project_id"), table_name="action_records")
    op.drop_table("action_records")
    op.drop_index(op.f("ix_widget_guides_perspective"), table_name="widget_guides")
    op.drop_table("widget_guides")
    op.drop_table("templates")
    op.drop_index(op.f("ix_projects_key"), table_name="projects")
    op.drop_table("projects")
    op.drop_table("perspective_guides")
    op.drop_table("connector_types")
    op.drop_index(op.f("ix_audit_logs_resource_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_project_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_category"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("artifact_definitions")
