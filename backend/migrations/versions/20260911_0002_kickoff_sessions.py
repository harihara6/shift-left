"""Feature Kickoff sessions: a PRD taken to a confirmed plan.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-11 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(op.f("ix_kickoff_sessions_actor"), table_name="kickoff_sessions")
    op.drop_index(op.f("ix_kickoff_sessions_project_id"), table_name="kickoff_sessions")
    op.drop_table("kickoff_sessions")
