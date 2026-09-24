"""Add user messages for parser provenance.

Revision ID: 0002_parser_messages
Revises: 0001_persistence_api
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_parser_messages"
down_revision = "0001_persistence_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["design_session.session_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("ix_message_session_id", "message", ["session_id"])
    op.create_index("ix_message_session_created", "message", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_table("message")
