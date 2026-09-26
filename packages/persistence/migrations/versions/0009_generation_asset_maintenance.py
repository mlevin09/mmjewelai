"""Add durable generation Asset maintenance progress.

Revision ID: 0009_generation_asset_maint
Revises: 0008_generation_recovery_retry
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_generation_asset_maint"
down_revision = "0008_generation_recovery_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.add_column(sa.Column("assets_reconciled_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("orphan_cleanup_completed_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_generation_run_reconcile_scan",
        "generation_run",
        ["status", "assets_reconciled_at", "completed_at"],
    )
    op.create_index(
        "ix_generation_run_cleanup_scan",
        "generation_run",
        ["status", "orphan_cleanup_completed_at", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_run_cleanup_scan", table_name="generation_run")
    op.drop_index("ix_generation_run_reconcile_scan", table_name="generation_run")
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.drop_column("orphan_cleanup_completed_at")
        batch_op.drop_column("assets_reconciled_at")
