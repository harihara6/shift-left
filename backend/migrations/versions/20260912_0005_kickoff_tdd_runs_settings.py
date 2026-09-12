"""Feature Kickoff: a technical design, run history, and service-wide defaults.

Three changes, all in service of running the same analysis several times while a requirement is
still moving:

* `kickoff_analyses.tdd` holds the drafted technical design and where it was published, for the
  analyses that asked for one. Null means no TDD was asked for - never an empty one.
* `kickoff_runs` keeps every draft whole. Until now a second run overwrote the first, taking the
  human edits on it with no way back; now the live plan is still the one people edit, and each
  draft is also recorded so two runs can be read and compared.
* `kickoff_settings` is one row of defaults a new analysis starts from (the TDD template and where
  it is written, the backlog and what its tickets carry, the standing instruction). It holds no
  credential - those stay in the connectors and the vault - so it is readable by any signed-in
  user and writable only by a platform admin. The row is created here so there is always exactly
  one to read and update.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-12 10:46:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kickoff_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tdd_template_url", sa.Text(), nullable=False),
        sa.Column("tdd_space_key", sa.String(length=64), nullable=False),
        sa.Column("tdd_parent_url", sa.Text(), nullable=False),
        sa.Column("tdd_sections", sa.JSON(), nullable=False),
        sa.Column("jira_project_url", sa.Text(), nullable=False),
        sa.Column("jira_defaults", sa.JSON(), nullable=False),
        sa.Column("analysis_prompt", sa.Text(), nullable=False),
        sa.Column("tdd_prompt", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Exactly one row, so reads never have to cope with its absence.
    op.execute(
        "INSERT INTO kickoff_settings "
        "(id, tdd_template_url, tdd_space_key, tdd_parent_url, tdd_sections, jira_project_url, "
        " jira_defaults, analysis_prompt, tdd_prompt, updated_by) "
        "VALUES (1, '', '', '', '[]', '', '{}', '', '', '')"
    )

    op.create_table(
        "kickoff_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("reader", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("tdd", sa.JSON(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["kickoff_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("kickoff_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_kickoff_runs_analysis_id"), ["analysis_id"], unique=False)

    with op.batch_alter_table("kickoff_analyses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tdd", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kickoff_analyses", schema=None) as batch_op:
        batch_op.drop_column("tdd")
    with op.batch_alter_table("kickoff_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_kickoff_runs_analysis_id"))
    op.drop_table("kickoff_runs")
    op.drop_table("kickoff_settings")
