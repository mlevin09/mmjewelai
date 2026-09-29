"""Add grouped visualization iterations and immutable result decisions.

Revision ID: 0010_visualization_iterations
Revises: 0009_generation_asset_maint
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_visualization_iterations"
down_revision = "0009_generation_asset_maint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visualization_iteration",
        sa.Column("iteration_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_revision_id"], ["prompt_revision.prompt_revision_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("iteration_id"),
    )
    op.create_index(
        "ix_visualization_iteration_session_id", "visualization_iteration", ["session_id"]
    )
    op.create_index(
        "ix_visualization_iteration_prompt_revision_id",
        "visualization_iteration",
        ["prompt_revision_id"],
    )
    op.create_index(
        "ix_visualization_iteration_prompt_content_hash",
        "visualization_iteration",
        ["prompt_content_hash"],
    )
    op.create_index(
        "ix_visualization_iteration_session_created",
        "visualization_iteration",
        ["session_id", "created_at"],
    )
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.add_column(sa.Column("iteration_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_generation_run_iteration",
            "visualization_iteration",
            ["iteration_id"],
            ["iteration_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_generation_run_iteration_id", ["iteration_id"])
    op.create_table(
        "visualization_selection",
        sa.Column("iteration_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("selected_by_principal_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('selected', 'rejected')", name="ck_visual_selection_decision"
        ),
        sa.CheckConstraint(
            "(decision = 'selected' AND asset_id IS NOT NULL) OR "
            "(decision = 'rejected' AND asset_id IS NULL)",
            name="ck_visual_selection_asset",
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.asset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["iteration_id"], ["visualization_iteration.iteration_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["selected_by_principal_id"], ["auth_principal.principal_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("iteration_id"),
    )
    op.create_index(
        "ix_visualization_selection_session_id", "visualization_selection", ["session_id"]
    )
    op.create_index("ix_visualization_selection_asset_id", "visualization_selection", ["asset_id"])
    op.create_index(
        "ix_visualization_selection_selected_by_principal_id",
        "visualization_selection",
        ["selected_by_principal_id"],
    )
    op.create_index(
        "ix_visual_selection_session_created",
        "visualization_selection",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("visualization_selection")
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.drop_index("ix_generation_run_iteration_id")
        batch_op.drop_constraint("fk_generation_run_iteration", type_="foreignkey")
        batch_op.drop_column("iteration_id")
    op.drop_table("visualization_iteration")
