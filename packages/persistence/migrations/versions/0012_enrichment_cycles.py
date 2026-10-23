"""Add durable Knowledge release pins and versioned enrichment cycles.

Revision ID: 0012_enrichment_cycles
Revises: 0011_iterative_edits
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_enrichment_cycles"
down_revision = "0011_iterative_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("design_session") as batch_op:
        batch_op.add_column(sa.Column("knowledge_package_id", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column("knowledge_artifact_version", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("knowledge_runtime_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("knowledge_validation_report_sha256", sa.String(length=64), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_design_session_knowledge_pin_complete",
            "(knowledge_package_id IS NULL AND knowledge_artifact_version IS NULL "
            "AND knowledge_runtime_sha256 IS NULL "
            "AND knowledge_validation_report_sha256 IS NULL) OR "
            "(knowledge_package_id IS NOT NULL AND knowledge_artifact_version IS NOT NULL "
            "AND knowledge_runtime_sha256 IS NOT NULL "
            "AND knowledge_validation_report_sha256 IS NOT NULL)",
        )

    op.create_table(
        "enrichment_cycle",
        sa.Column("enrichment_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("specification_revision_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_package_id", sa.String(length=200), nullable=False),
        sa.Column("knowledge_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("knowledge_runtime_sha256", sa.String(length=64), nullable=False),
        sa.Column("knowledge_validation_report_sha256", sa.String(length=64), nullable=False),
        sa.Column("enrichment_version", sa.String(length=32), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cycle_number >= 1", name="ck_enrichment_cycle_number_positive"),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["specification_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("enrichment_cycle_id"),
        sa.UniqueConstraint(
            "session_id", "cycle_number", name="uq_enrichment_cycle_session_number"
        ),
    )
    op.create_index("ix_enrichment_cycle_session_id", "enrichment_cycle", ["session_id"])
    op.create_index(
        "ix_enrichment_cycle_specification_revision_id",
        "enrichment_cycle",
        ["specification_revision_id"],
    )
    op.create_index("ix_enrichment_cycle_content_hash", "enrichment_cycle", ["content_hash"])
    op.create_index(
        "ix_enrichment_cycle_session_created",
        "enrichment_cycle",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("enrichment_cycle")
    with op.batch_alter_table("design_session") as batch_op:
        batch_op.drop_constraint("ck_design_session_knowledge_pin_complete", type_="check")
        batch_op.drop_column("knowledge_validation_report_sha256")
        batch_op.drop_column("knowledge_runtime_sha256")
        batch_op.drop_column("knowledge_artifact_version")
        batch_op.drop_column("knowledge_package_id")
