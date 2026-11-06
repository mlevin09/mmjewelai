"""Owner-approved logical session deletion; retain every dependent record."""

import sqlalchemy as sa
from alembic import op

revision = "0020_session_retirement"
down_revision = "0019_prompt_completion"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("design_session") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deleted_by_principal_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_session_deletion_principal",
            "auth_principal",
            ["deleted_by_principal_id"],
            ["principal_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_session_deletion_complete",
            "(deleted_at IS NULL AND deleted_by_principal_id IS NULL) OR "
            "(deleted_at IS NOT NULL AND deleted_by_principal_id IS NOT NULL)",
        )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT 1 FROM design_session WHERE deleted_at IS NOT NULL LIMIT 1")
    ):
        raise RuntimeError("Session tombstones require a reviewed retention plan before downgrade")
    with op.batch_alter_table("design_session") as batch:
        batch.drop_constraint("ck_session_deletion_complete", type_="check")
        batch.drop_constraint("fk_session_deletion_principal", type_="foreignkey")
        batch.drop_column("deleted_by_principal_id")
        batch.drop_column("deleted_at")
