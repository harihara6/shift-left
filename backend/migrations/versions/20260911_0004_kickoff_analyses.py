"""Feature Kickoff analyses replace kickoff sessions.

The seven-step kickoff saves an analysis per feature (PRD, repos, dependencies, compliance, API
docs, third parties, plan and backlog). The old sessions were read from example pages, so they are
dropped rather than carried over. The kickoff guide rows are removed with them: they describe the
old page, and startup seeds the new ones.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-11 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_kickoff_sessions_actor"), table_name="kickoff_sessions")
    op.drop_index(op.f("ix_kickoff_sessions_project_id"), table_name="kickoff_sessions")
    op.drop_table("kickoff_sessions")
    op.execute("DELETE FROM widget_guides WHERE perspective = 'kickoff'")
    op.execute("DELETE FROM perspective_guides WHERE perspective = 'kickoff'")

    op.create_table(
        "kickoff_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("backlog", sa.JSON(), nullable=True),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kickoff_analyses_project_id"), "kickoff_analyses", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_kickoff_analyses_project_id"), table_name="kickoff_analyses")
    op.drop_table("kickoff_analyses")
    op.create_table(
        "kickoff_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("page_title", sa.String(length=300), nullable=False),
        sa.Column("page_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("reader", sa.String(length=16), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(length=160), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kickoff_sessions_project_id"), "kickoff_sessions", ["project_id"], unique=False)
    op.create_index(op.f("ix_kickoff_sessions_actor"), "kickoff_sessions", ["actor"], unique=False)
