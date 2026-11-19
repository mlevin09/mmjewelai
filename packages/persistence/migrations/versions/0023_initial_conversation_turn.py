"""US-01 immutable input and write-once delivered conversational reply."""

import sqlalchemy as sa
from alembic import op

revision = "0023_initial_conversation_turn"
down_revision = "0022_first_conversation_turn"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "initial_conversation_turn",
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("design_session.session_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organization.organization_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("message.message_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("design_id", sa.Uuid(), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(), nullable=False),
        sa.Column("result_revision_id", sa.Uuid(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("reply_payload", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("reply_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("turn_id", name="uq_initial_conversation_turn_id"),
        sa.CheckConstraint(
            "(reply_payload IS NULL) = (reply_hash IS NULL)",
            name="ck_initial_conversation_delivery_pair",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "parent_revision_id", "design_id"],
            [
                "specification_revision.session_id",
                "specification_revision.revision_id",
                "specification_revision.design_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "result_revision_id", "design_id"],
            [
                "specification_revision.session_id",
                "specification_revision.revision_id",
                "specification_revision.design_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    op.execute("""
CREATE FUNCTION protect_initial_conversation_turn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Initial conversation history is immutable'; END IF;
  IF (to_jsonb(OLD) - 'reply_payload' - 'reply_hash') IS DISTINCT FROM
     (to_jsonb(NEW) - 'reply_payload' - 'reply_hash') OR
     OLD.reply_payload IS NOT NULL OR NEW.reply_payload IS NULL OR NEW.reply_hash IS NULL
  THEN RAISE EXCEPTION 'Initial conversation source/delivery is immutable'; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER initial_conversation_immutable BEFORE UPDATE OR DELETE ON initial_conversation_turn
FOR EACH ROW EXECUTE FUNCTION protect_initial_conversation_turn();
""")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT 1 FROM initial_conversation_turn LIMIT 1")):
        raise RuntimeError(
            "US-01 retained input/reply requires reviewed retention before downgrade"
        )
    op.drop_table("initial_conversation_turn")
    op.execute("DROP FUNCTION protect_initial_conversation_turn()")
