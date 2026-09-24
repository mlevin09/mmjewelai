"""Add immutable generation runs and explicit lifecycle state.

Revision ID: 0004_generation_runs
Revises: 0003_prompt_revisions
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_generation_runs"
down_revision = "0003_prompt_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_run",
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_content_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=100), nullable=False),
        sa.Column("profile_version", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("parent_generation_run_id", sa.Uuid(), nullable=True),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt >= 1", name="ck_generation_run_attempt_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_generation_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["parent_generation_run_id"],
            ["generation_run.generation_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_revision_id"],
            ["prompt_revision.prompt_revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("generation_run_id"),
    )
    op.create_index("ix_generation_run_session_id", "generation_run", ["session_id"])
    op.create_index(
        "ix_generation_run_prompt_revision_id", "generation_run", ["prompt_revision_id"]
    )
    op.create_index(
        "ix_generation_run_prompt_content_hash", "generation_run", ["prompt_content_hash"]
    )
    op.create_index("ix_generation_run_status", "generation_run", ["status"])
    op.create_index(
        "ix_generation_run_session_created", "generation_run", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("generation_run")
