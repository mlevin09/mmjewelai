"""Admit preparation2 without rewriting immutable preparation1 records.

F04 activation and execution on shared environments require separate authorization.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_f04_preparation_v2"
down_revision = "0017_knowledge_release_bindings"
branch_labels = None
depends_on = None


def _replace_check(predicate):
    if op.get_bind().dialect.name == "sqlite":
        # Only portable test databases use Alembic's supported batch replacement.
        with op.batch_alter_table("generation_preparation") as batch:
            batch.drop_constraint("ck_preparation_version", type_="check")
            batch.create_check_constraint("ck_preparation_version", predicate)
    else:
        op.drop_constraint("ck_preparation_version", "generation_preparation", type_="check")
        op.create_check_constraint("ck_preparation_version", "generation_preparation", predicate)


def upgrade():
    _replace_check("schema_version IN ('1.0.0', '2.0.0')")


def downgrade():
    # Check before any DDL. Never remove or reinterpret a retained new-version record.
    exists = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM generation_preparation WHERE schema_version = '2.0.0')"
        )
    )
    if exists:
        raise RuntimeError("Preparation2 records prevent safe downgrade; retain dual readers")
    _replace_check("schema_version = '1.0.0'")
