"""Activate generation recovery and explicit retry lineage.

Revision ID: 0008_generation_recovery_retry_lineage
Revises: 0007_generation_dispatch_outbox
"""

from alembic import op

revision = "0008_generation_recovery_retry_lineage"
down_revision = "0007_generation_dispatch_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.create_check_constraint(
            "ck_generation_run_retry_lineage",
            "(attempt = 1 AND parent_generation_run_id IS NULL) OR "
            "(attempt > 1 AND parent_generation_run_id IS NOT NULL)",
        )
        batch_op.create_unique_constraint(
            "uq_generation_run_direct_retry_child", ["parent_generation_run_id"]
        )
    op.create_index(
        "ix_generation_run_status_started",
        "generation_run",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_run_status_started", table_name="generation_run")
    with op.batch_alter_table("generation_run") as batch_op:
        batch_op.drop_constraint("uq_generation_run_direct_retry_child", type_="unique")
        batch_op.drop_constraint("ck_generation_run_retry_lineage", type_="check")
