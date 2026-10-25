"""Add reference binding and visualization verification persistence.

Revision ID: 0015_reference_verification
Revises: 0014_clarification_plans
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_reference_verification"
down_revision = "0014_clarification_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_binding",
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.organization_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["design_session.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.asset_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("binding_id"),
    )
    op.create_index(
        "ix_reference_binding_organization_id",
        "reference_binding",
        ["organization_id"],
    )
    op.create_index("ix_reference_binding_session_id", "reference_binding", ["session_id"])
    op.create_index("ix_reference_binding_asset", "reference_binding", ["asset_id"])
    op.create_index(
        "ix_reference_binding_content_hash", "reference_binding", ["content_hash"]
    )
    op.create_index(
        "ix_reference_binding_session_created",
        "reference_binding",
        ["session_id", "created_at"],
    )

    op.create_table(
        "visualization_verification",
        sa.Column("verification_id", sa.String(length=200), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("design_revision_id", sa.Uuid(), nullable=True),
        sa.Column("previous_asset_id", sa.Uuid(), nullable=True),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.organization_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["design_session.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"], ["generation_run.generation_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.asset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["design_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_asset_id"], ["asset.asset_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("verification_id"),
    )
    op.create_index(
        "ix_visualization_verification_organization_id",
        "visualization_verification",
        ["organization_id"],
    )
    op.create_index(
        "ix_visualization_verification_session_id",
        "visualization_verification",
        ["session_id"],
    )
    op.create_index(
        "ix_visualization_verification_generation_run",
        "visualization_verification",
        ["generation_run_id"],
    )
    op.create_index(
        "ix_visualization_verification_asset",
        "visualization_verification",
        ["asset_id"],
    )
    op.create_index(
        "ix_visualization_verification_design_revision_id",
        "visualization_verification",
        ["design_revision_id"],
    )
    op.create_index(
        "ix_visualization_verification_content_hash",
        "visualization_verification",
        ["content_hash"],
    )
    op.create_index(
        "ix_visualization_verification_session_created",
        "visualization_verification",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("visualization_verification")
    op.drop_table("reference_binding")
