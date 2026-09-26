"""Add durable generation dispatch outbox.

Revision ID: 0007_generation_dispatch_outbox
Revises: 0006_auth_membership
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_generation_dispatch_outbox"
down_revision = "0006_auth_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_dispatch_outbox",
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["generation_run_id"], ["generation_run.generation_run_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("generation_run_id"),
    )
    op.create_index(
        "ix_generation_dispatch_pending",
        "generation_dispatch_outbox",
        ["published_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("generation_dispatch_outbox")
