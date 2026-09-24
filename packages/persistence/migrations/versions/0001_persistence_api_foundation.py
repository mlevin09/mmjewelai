"""Create persistence and API foundation tables.

Revision ID: 0001_persistence_api
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_persistence_api"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id"),
    )
    op.create_table(
        "project",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.organization_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_index("ix_project_organization_id", "project", ["organization_id"])
    op.create_table(
        "design_session",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.String(length=80), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=False),
        sa.Column("design_schema_version", sa.String(length=32), nullable=False),
        sa.Column("role_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("dictionary_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("question_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("rules_artifact_version", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.project_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_design_session_project_id", "design_session", ["project_id"])
    op.create_index(
        "ix_design_session_current_revision_id", "design_session", ["current_revision_id"]
    )
    op.create_table(
        "specification_revision",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("design_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint("session_id", "parent_revision_id", name="uq_revision_session_parent"),
        sa.UniqueConstraint("session_id", "revision_number", name="uq_revision_session_number"),
    )
    op.create_index(
        "ix_revision_session_created",
        "specification_revision",
        ["session_id", "created_at"],
    )
    op.create_index("ix_specification_revision_design_id", "specification_revision", ["design_id"])
    op.create_index(
        "ix_specification_revision_session_id", "specification_revision", ["session_id"]
    )
    op.create_table(
        "question_event",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("specification_revision_id", sa.Uuid(), nullable=False),
        sa.Column("semantic_question_id", sa.String(length=100), nullable=False),
        sa.Column("rules_artifact_version", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=False),
        sa.Column("concrete_target", sa.String(length=240), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("trace_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["specification_revision_id"],
            ["specification_revision.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_question_event_session_id", "question_event", ["session_id"])
    op.create_index(
        "ix_question_event_specification_revision_id",
        "question_event",
        ["specification_revision_id"],
    )
    op.create_index(
        "ix_question_event_session_created", "question_event", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("question_event")
    op.drop_table("specification_revision")
    op.drop_table("design_session")
    op.drop_table("project")
    op.drop_table("organization")
