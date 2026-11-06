"""Opt-in completion lineage. Shared migration requires separate approval."""

import sqlalchemy as sa
from alembic import op

revision = "0019_prompt_completion"
down_revision = "0018_f04_preparation_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prompt_completion",
        sa.Column("completion_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organization.organization_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("design_session.session_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cycle_id",
            sa.Uuid(),
            sa.ForeignKey("enrichment_cycle.enrichment_cycle_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("message.message_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.Uuid(),
            sa.ForeignKey("auth_principal.principal_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "request_id", name="uq_completion_request"),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_completion_sequence"),
    )
    op.create_index("ix_completion_session_time", "prompt_completion", ["session_id", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION protect_prompt_completion() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Prompt completion is immutable'; END; $$;
CREATE TRIGGER completion_immutable BEFORE UPDATE OR DELETE
ON prompt_completion
FOR EACH ROW EXECUTE FUNCTION protect_prompt_completion();""")


def downgrade():
    raise RuntimeError(
        "Completion online downgrade is unsupported; requires reviewed retention plan"
    )
