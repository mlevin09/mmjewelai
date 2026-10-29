"""Immutable explicit Knowledge contract bindings; no historical payload rewrites."""

import sqlalchemy as sa
from alembic import op

revision = "0017_knowledge_release_bindings"
down_revision = "0016_generation_preparations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "enrichment_cycle", sa.Column("knowledge_contract_version", sa.String(32), nullable=True)
    )
    op.create_table(
        "knowledge_release_binding",
        sa.Column("session_id", sa.Uuid(), primary_key=True),
        sa.Column("enrichment_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("specification_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organization.organization_id"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id", "enrichment_cycle_id", "cycle_number", "specification_revision_id"],
            [
                "enrichment_cycle.session_id",
                "enrichment_cycle.enrichment_cycle_id",
                "enrichment_cycle.cycle_number",
                "enrichment_cycle.specification_revision_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("cycle_number = 1", name="ck_knowledge_binding_initial_cycle"),
    )
    op.execute("""
CREATE FUNCTION prevent_knowledge_binding_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Knowledge release binding is immutable'; END;
$$;
CREATE TRIGGER knowledge_binding_immutable BEFORE UPDATE OR DELETE ON knowledge_release_binding
FOR EACH ROW EXECUTE FUNCTION prevent_knowledge_binding_mutation();
""")


def downgrade():
    # An old runtime cannot interpret v1.1 sessions. Never destroy retained bindings.
    raise RuntimeError(
        "Knowledge binding online downgrade is unsupported; requires a reviewed retention plan"
    )
