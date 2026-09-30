"""Add iterative edit and source-Asset lineage.

Revision ID: 0011_iterative_edits
Revises: 0010_visualization_iterations
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_iterative_edits"
down_revision = "0010_visualization_iterations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "iterative_edit",
        sa.Column("edit_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("starting_revision_id", sa.Uuid(), nullable=False),
        sa.Column("initial_message_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["asset.asset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["starting_revision_id"], ["specification_revision.revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["initial_message_id"], ["message.message_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("edit_id"),
    )
    for column in ("session_id", "source_asset_id", "starting_revision_id", "initial_message_id"):
        op.create_index(f"ix_iterative_edit_{column}", "iterative_edit", [column])
    op.create_index(
        "ix_iterative_edit_session_created", "iterative_edit", ["session_id", "created_at"]
    )
    with op.batch_alter_table("visualization_iteration") as batch_op:
        batch_op.add_column(sa.Column("iterative_edit_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_visualization_iteration_iterative_edit",
            "iterative_edit",
            ["iterative_edit_id"],
            ["edit_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_visualization_iteration_iterative_edit_id",
            ["iterative_edit_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("visualization_iteration") as batch_op:
        batch_op.drop_index("ix_visualization_iteration_iterative_edit_id")
        batch_op.drop_constraint("fk_visualization_iteration_iterative_edit", type_="foreignkey")
        batch_op.drop_column("iterative_edit_id")
    op.drop_table("iterative_edit")
