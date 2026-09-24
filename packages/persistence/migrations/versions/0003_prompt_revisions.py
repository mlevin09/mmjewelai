"""Add prompt artifact pin and immutable prompt revisions.

Revision ID: 0003_prompt_revisions
Revises: 0002_parser_messages
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_prompt_revisions"
down_revision = "0002_parser_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "design_session",
        sa.Column(
            "prompt_artifact_version",
            sa.String(length=32),
            nullable=False,
            server_default="1.0.0",
        ),
    )
    op.create_table(
        "prompt_revision",
        sa.Column("prompt_revision_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("specification_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=32), nullable=False),
        sa.Column("compiler_version", sa.String(length=32), nullable=False),
        sa.Column("template_id", sa.String(length=80), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column("template_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("compiled_text", sa.String(), nullable=False),
        sa.Column("structured_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["specification_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("prompt_revision_id"),
    )
    op.create_index("ix_prompt_revision_session_id", "prompt_revision", ["session_id"])
    op.create_index(
        "ix_prompt_revision_specification_revision_id",
        "prompt_revision",
        ["specification_revision_id"],
    )
    op.create_index("ix_prompt_revision_content_hash", "prompt_revision", ["content_hash"])
    op.create_index(
        "ix_prompt_revision_session_created",
        "prompt_revision",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("prompt_revision")
    with op.batch_alter_table("design_session") as batch_op:
        batch_op.drop_column("prompt_artifact_version")
