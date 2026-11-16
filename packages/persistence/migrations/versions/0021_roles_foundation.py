"""One current PostgreSQL Roles catalog; no legacy-session purge.

Revision ID: 0021_roles_foundation
Revises: 0020_session_retirement
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_roles_foundation"
down_revision = "0020_session_retirement"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "roles",
        sa.Column("role_id", sa.String(16), primary_key=True),
        sa.Column("name_ru", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("merged_from_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("role_data", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_roles_status"),
        sa.CheckConstraint("revision >= 1", name="ck_roles_revision"),
    )
    op.create_index("ix_roles_status", "roles", ["status"])
    # Legacy rows are retained. NOT VALID avoids destructive cleanup yet enforces new writes.
    op.create_foreign_key(
        "fk_design_session_current_role",
        "design_session",
        "roles",
        ["role_id"],
        ["role_id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    import json
    from datetime import UTC, datetime
    from importlib.resources import files

    from jewelai_persistence.models import RoleRow

    records = json.loads(
        files("jewelai_persistence").joinpath("role_seed.json").read_text(encoding="utf-8")
    )
    op.create_check_constraint(
        "ck_roles_id",
        "roles",
        "role_id IN ('RR-C02', 'RR-C04', 'RR-C06', 'RR-C09', 'RR-C10', 'RR-C11'"
        ", 'RR-C12', 'RR-C14', 'RR-C15', 'RR-C16', 'RR-C17', 'RR-C18', 'RR-C20'"
        ", 'RR-C21', 'RR-C26', 'RR-C22', 'RR-C27', 'RR-C28', 'RR-C23', 'RR-C24'"
        ", 'RR-C25')",
    )
    op.create_check_constraint("ck_roles_name", "roles", "trim(name_ru) <> ''")
    op.create_check_constraint("ck_roles_timestamps", "roles", "updated_at >= created_at")
    now = datetime.now(UTC)
    op.get_bind().execute(
        sa.insert(RoleRow.__table__),
        [dict(r, revision=1, created_at=now, updated_at=now) for r in records],
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT 1 FROM design_session JOIN roles USING (role_id) LIMIT 1")
    ) or op.get_bind().scalar(sa.text("SELECT 1 FROM roles WHERE revision > 1 LIMIT 1")):
        raise RuntimeError("Current Roles data requires reviewed retention before downgrade")
    op.drop_constraint("fk_design_session_current_role", "design_session", type_="foreignkey")
    op.drop_index("ix_roles_status", table_name="roles")
    op.drop_table("roles")
