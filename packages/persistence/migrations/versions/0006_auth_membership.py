"""Add external principals and organization memberships.

Revision ID: 0006_auth_membership
Revises: 0005_assets
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_auth_membership"
down_revision = "0005_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_principal",
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("principal_id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_principal_issuer_subject"),
    )
    op.create_table(
        "organization_membership",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_membership_role"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.organization_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["principal_id"], ["auth_principal.principal_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("organization_id", "principal_id"),
    )
    op.create_index("ix_membership_organization", "organization_membership", ["organization_id"])
    op.create_index("ix_membership_principal", "organization_membership", ["principal_id"])


def downgrade() -> None:
    op.drop_table("organization_membership")
    op.drop_table("auth_principal")
