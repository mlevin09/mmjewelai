"""Add private asset metadata and lifecycle.

Revision ID: 0005_assets
Revises: 0004_generation_runs
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_assets"
down_revision = "0004_generation_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=True),
        sa.Column("generation_output_ordinal", sa.Integer(), nullable=True),
        sa.Column("provider_output_id", sa.String(length=240), nullable=True),
        sa.Column("parent_asset_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.CheckConstraint("kind IN ('reference', 'generated')", name="ck_asset_kind"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_asset_status"),
        sa.CheckConstraint("byte_size > 0", name="ck_asset_byte_size_positive"),
        sa.CheckConstraint(
            "generation_output_ordinal IS NULL OR generation_output_ordinal BETWEEN 1 AND 4",
            name="ck_asset_generation_ordinal",
        ),
        sa.CheckConstraint(
            "parent_asset_id IS NULL OR parent_asset_id != asset_id", name="ck_asset_parent"
        ),
        sa.CheckConstraint(
            "(kind = 'reference' AND generation_run_id IS NULL "
            "AND generation_output_ordinal IS NULL AND provider_output_id IS NULL) OR "
            "(kind = 'generated' AND generation_run_id IS NOT NULL "
            "AND generation_output_ordinal IS NOT NULL)",
            name="ck_asset_kind_lineage",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND ready_at IS NULL AND failed_at IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL AND failed_at IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL) OR "
            "(status = 'failed' AND ready_at IS NULL AND failed_at IS NOT NULL "
            "AND error_code IS NOT NULL AND error_detail IS NOT NULL)",
            name="ck_asset_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["generation_run_id"], ["generation_run.generation_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.organization_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["parent_asset_id"], ["asset.asset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["project.project_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("asset_id"),
        sa.UniqueConstraint("object_key", name="uq_asset_object_key"),
        sa.UniqueConstraint(
            "generation_run_id",
            "generation_output_ordinal",
            name="uq_asset_generation_output",
        ),
    )
    op.create_index("ix_asset_organization_id", "asset", ["organization_id"])
    op.create_index("ix_asset_project_id", "asset", ["project_id"])
    op.create_index("ix_asset_session_id", "asset", ["session_id"])
    op.create_index("ix_asset_status", "asset", ["status"])
    op.create_index("ix_asset_content_hash", "asset", ["content_hash"])
    op.create_index("ix_asset_generation_run_id", "asset", ["generation_run_id"])
    op.create_index("ix_asset_session_created", "asset", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_table("asset")
