"""Add immutable clarification plans bound to enrichment cycles.

Revision ID: 0014_clarification_plans
Revises: 0013_enrichment_decisions
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_clarification_plans"
down_revision = "0013_enrichment_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clarification_plan",
        sa.Column("clarification_plan_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("enrichment_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("specification_revision_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.String(length=32), nullable=False),
        sa.Column("knowledge_package_id", sa.String(length=200), nullable=False),
        sa.Column("knowledge_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("knowledge_runtime_sha256", sa.String(length=64), nullable=False),
        sa.Column("knowledge_validation_report_sha256", sa.String(length=64), nullable=False),
        sa.Column("dictionary_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("question_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("rules_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("plan_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.organization_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["enrichment_cycle_id"],
            ["enrichment_cycle.enrichment_cycle_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["specification_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("clarification_plan_id"),
        sa.UniqueConstraint("enrichment_cycle_id", name="uq_clarification_plan_enrichment_cycle"),
    )
    op.create_index(
        "ix_clarification_plan_organization_id", "clarification_plan", ["organization_id"]
    )
    op.create_index("ix_clarification_plan_session_id", "clarification_plan", ["session_id"])
    op.create_index(
        "ix_clarification_plan_enrichment_cycle_id",
        "clarification_plan",
        ["enrichment_cycle_id"],
    )
    op.create_index(
        "ix_clarification_plan_specification_revision_id",
        "clarification_plan",
        ["specification_revision_id"],
    )
    op.create_index("ix_clarification_plan_content_hash", "clarification_plan", ["content_hash"])
    op.create_index(
        "ix_clarification_plan_session_created",
        "clarification_plan",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_clarification_plan_session_revision",
        "clarification_plan",
        ["session_id", "specification_revision_id"],
    )
    with op.batch_alter_table("clarification_answer") as batch:
        batch.add_column(sa.Column("clarification_plan_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_clarification_answer_plan",
            "clarification_plan",
            ["clarification_plan_id"],
            ["clarification_plan_id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_clarification_answer_clarification_plan_id", ["clarification_plan_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("clarification_answer") as batch:
        batch.drop_index("ix_clarification_answer_clarification_plan_id")
        batch.drop_constraint("fk_clarification_answer_plan", type_="foreignkey")
        batch.drop_column("clarification_plan_id")
    op.drop_table("clarification_plan")
