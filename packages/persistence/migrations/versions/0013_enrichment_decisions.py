"""Add durable clarification decisions and user corrections.

Revision ID: 0013_enrichment_decisions
Revises: 0012_enrichment_cycles
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_enrichment_decisions"
down_revision = "0012_enrichment_cycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clarification_answer",
        sa.Column("answer_record_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("plan_content_hash", sa.String(length=64), nullable=False),
        sa.Column("clarification_id", sa.String(length=200), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=False),
        sa.Column("new_revision_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("answer_hash", sa.String(length=64), nullable=False),
        sa.Column("knowledge_package_id", sa.String(length=200), nullable=False),
        sa.Column("knowledge_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("knowledge_runtime_sha256", sa.String(length=64), nullable=False),
        sa.Column("knowledge_validation_report_sha256", sa.String(length=64), nullable=False),
        sa.Column("question_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("rules_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("answer_record_id"),
        sa.UniqueConstraint(
            "session_id",
            "plan_content_hash",
            "clarification_id",
            name="uq_clarification_answer_question",
        ),
    )
    op.create_index("ix_clarification_answer_session_id", "clarification_answer", ["session_id"])
    op.create_index(
        "ix_clarification_answer_previous_revision_id",
        "clarification_answer",
        ["previous_revision_id"],
    )
    op.create_index(
        "ix_clarification_answer_new_revision_id",
        "clarification_answer",
        ["new_revision_id"],
    )
    op.create_index("ix_clarification_answer_answer_hash", "clarification_answer", ["answer_hash"])
    op.create_index(
        "ix_clarification_answer_content_hash", "clarification_answer", ["content_hash"]
    )
    op.create_index(
        "ix_clarification_answer_session_created",
        "clarification_answer",
        ["session_id", "created_at"],
    )

    op.create_table(
        "user_correction",
        sa.Column("correction_record_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.String(length=2000), nullable=False),
        sa.Column("source_identity_hash", sa.String(length=64), nullable=False),
        sa.Column("correction_text", sa.String(length=2000), nullable=False),
        sa.Column("previous_revision_id", sa.Uuid(), nullable=False),
        sa.Column("new_revision_id", sa.Uuid(), nullable=True),
        sa.Column("previous_enrichment_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("next_enrichment_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("knowledge_package_id", sa.String(length=200), nullable=False),
        sa.Column("knowledge_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("knowledge_runtime_sha256", sa.String(length=64), nullable=False),
        sa.Column("knowledge_validation_report_sha256", sa.String(length=64), nullable=False),
        sa.Column("dictionary_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_template_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["previous_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["previous_enrichment_cycle_id"],
            ["enrichment_cycle.enrichment_cycle_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["next_enrichment_cycle_id"],
            ["enrichment_cycle.enrichment_cycle_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("correction_record_id"),
        sa.UniqueConstraint("session_id", "source_identity_hash", name="uq_user_correction_source"),
        sa.UniqueConstraint("next_enrichment_cycle_id", name="uq_user_correction_next_cycle"),
    )
    op.create_index("ix_user_correction_session_id", "user_correction", ["session_id"])
    op.create_index(
        "ix_user_correction_previous_revision_id",
        "user_correction",
        ["previous_revision_id"],
    )
    op.create_index("ix_user_correction_new_revision_id", "user_correction", ["new_revision_id"])
    op.create_index(
        "ix_user_correction_previous_enrichment_cycle_id",
        "user_correction",
        ["previous_enrichment_cycle_id"],
    )
    op.create_index(
        "ix_user_correction_next_enrichment_cycle_id",
        "user_correction",
        ["next_enrichment_cycle_id"],
    )
    op.create_index("ix_user_correction_semantic_hash", "user_correction", ["semantic_hash"])
    op.create_index("ix_user_correction_content_hash", "user_correction", ["content_hash"])
    op.create_index(
        "ix_user_correction_session_created",
        "user_correction",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("user_correction")
    op.drop_table("clarification_answer")
