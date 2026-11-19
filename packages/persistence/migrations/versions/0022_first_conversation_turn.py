"""Opt-in ST-01 immutable source binding/reply; existing cycle payloads unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0022_first_conversation_turn"
down_revision = "0021_roles_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enrichment_cycle", sa.Column("source_contract", sa.String(80), nullable=True))
    op.create_table(
        "first_conversation_turn",
        sa.Column("session_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organization.organization_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("message.message_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parent_revision_id",
            sa.Uuid(),
            sa.ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("enrichment_cycle_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("specification_revision_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("cycle_number = 1", name="ck_first_conversation_initial"),
    )
    op.execute("""
CREATE FUNCTION prevent_first_turn_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'First conversation turn is immutable'; END;
$$;
CREATE TRIGGER first_turn_immutable BEFORE UPDATE OR DELETE ON first_conversation_turn
FOR EACH ROW EXECUTE FUNCTION prevent_first_turn_mutation();
CREATE TRIGGER first_turn_source_contract_immutable
BEFORE UPDATE OF source_contract ON enrichment_cycle
FOR EACH ROW WHEN (OLD.source_contract IS DISTINCT FROM NEW.source_contract)
EXECUTE FUNCTION prevent_first_turn_mutation();
""")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT 1 FROM first_conversation_turn LIMIT 1")):
        raise RuntimeError("ST-01 retained history requires reviewed retention before downgrade")
    op.execute("DROP TRIGGER first_turn_source_contract_immutable ON enrichment_cycle")
    op.execute("DROP TRIGGER first_turn_immutable ON first_conversation_turn")
    op.execute("DROP FUNCTION prevent_first_turn_mutation()")
    op.drop_table("first_conversation_turn")
    op.drop_column("enrichment_cycle", "source_contract")
