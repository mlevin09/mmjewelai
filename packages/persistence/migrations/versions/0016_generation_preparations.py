"""Retain canonical preparations and scoped idempotent commands without dispatch.

Revision ID: 0016_generation_preparations
Revises: 0015_reference_verification

Additive only. No historical inputs are rewritten. Run/iteration input cutover belongs to B3.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_generation_preparations"
down_revision = "0015_reference_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Each tuple already contains a primary key, so these add scope-addressable keys, not new facts.
    op.create_unique_constraint(
        "uq_project_organization", "project", ["project_id", "organization_id"]
    )
    op.create_unique_constraint(
        "uq_design_session_project", "design_session", ["session_id", "project_id"]
    )
    op.create_unique_constraint(
        "uq_revision_session_design",
        "specification_revision",
        ["session_id", "revision_id", "design_id"],
    )
    op.create_unique_constraint(
        "uq_cycle_preparation_binding",
        "enrichment_cycle",
        ["session_id", "enrichment_cycle_id", "cycle_number", "specification_revision_id"],
    )
    op.execute("""
CREATE TABLE generation_preparation (
 preparation_id UUID NOT NULL PRIMARY KEY,
 organization_id UUID NOT NULL REFERENCES organization(organization_id) ON DELETE RESTRICT,
 project_id UUID NOT NULL,
 session_id UUID NOT NULL,
 design_id UUID NOT NULL,
 product_state_revision_id UUID NOT NULL,
 enrichment_cycle_id UUID NOT NULL,
 enrichment_cycle_number INTEGER NOT NULL,
 enrichment_result_hash VARCHAR(64) NOT NULL,
 schema_version VARCHAR(32) NOT NULL,
 source_handoff_hash VARCHAR(64) NOT NULL,
 source_bytes_sha256 VARCHAR(64) NOT NULL,
 gate_evidence_hash VARCHAR(64) NOT NULL,
 rendering_hash VARCHAR(64) NOT NULL,
 artifact_hash VARCHAR(64) NOT NULL,
 source_bytes BYTEA NOT NULL,
 artifact_bytes BYTEA NOT NULL,
 artifact_payload JSON NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT uq_preparation_scope UNIQUE(preparation_id, organization_id, session_id),
 FOREIGN KEY(project_id, organization_id)
   REFERENCES project(project_id, organization_id) ON DELETE RESTRICT,
 FOREIGN KEY(session_id, project_id)
   REFERENCES design_session(session_id, project_id) ON DELETE RESTRICT,
 FOREIGN KEY(session_id, product_state_revision_id, design_id)
   REFERENCES specification_revision(session_id, revision_id, design_id) ON DELETE RESTRICT,
 FOREIGN KEY(session_id, enrichment_cycle_id, enrichment_cycle_number, product_state_revision_id)
   REFERENCES enrichment_cycle(
     session_id, enrichment_cycle_id, cycle_number, specification_revision_id) ON DELETE RESTRICT,
 CONSTRAINT ck_preparation_version CHECK(schema_version = '1.0.0'),
 CONSTRAINT ck_preparation_artifact_size CHECK(length(artifact_bytes) <= 2097152)
)
""")
    op.create_index(
        "ix_preparation_session_created", "generation_preparation", ["session_id", "created_at"]
    )
    for field in (
        "enrichment_result_hash",
        "source_handoff_hash",
        "source_bytes_sha256",
        "gate_evidence_hash",
        "rendering_hash",
        "artifact_hash",
    ):
        op.create_check_constraint(
            f"ck_preparation_{field}", "generation_preparation", f"{field} ~ '^[0-9a-f]{{64}}$'"
        )
    op.execute("""
CREATE TABLE generation_command (
 organization_id UUID NOT NULL,
 session_id UUID NOT NULL,
 command VARCHAR(80) NOT NULL,
 idempotency_key UUID NOT NULL,
 request_hash VARCHAR(64) NOT NULL,
 preparation_id UUID NOT NULL,
 response_bytes BYTEA NOT NULL,
 response_hash VARCHAR(64) NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY(organization_id, session_id, command, idempotency_key),
 FOREIGN KEY(preparation_id, organization_id, session_id)
   REFERENCES generation_preparation(preparation_id, organization_id, session_id) ON DELETE RESTRICT
)
""")
    for field in ("request_hash", "response_hash"):
        op.create_check_constraint(
            f"ck_generation_command_{field}", "generation_command", f"{field} ~ '^[0-9a-f]{{64}}$'"
        )
    op.execute("""
CREATE FUNCTION jewelai_reject_generation_input_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'immutable_generation_input';
END;
$$
""")
    for table in ("generation_preparation", "generation_command"):
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION jewelai_reject_generation_input_mutation()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Never destroy retained professional input or successful command history during rollback.
    # PostgreSQL holds both locks through Alembic's transactional DDL. Match insertion order:
    # a writer which already inserted a preparation must finish before we check either table.
    bind.execute(
        sa.text("LOCK TABLE generation_preparation, generation_command IN ACCESS EXCLUSIVE MODE")
    )
    if any(
        bind.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        for table in (
            "generation_command",
            "generation_preparation",
        )
    ):
        raise RuntimeError("Populated preparation history cannot be downgraded")
    op.drop_table("generation_command")
    op.drop_table("generation_preparation")
    op.execute("DROP FUNCTION jewelai_reject_generation_input_mutation()")
    for table, name in (
        ("enrichment_cycle", "uq_cycle_preparation_binding"),
        ("specification_revision", "uq_revision_session_design"),
        ("design_session", "uq_design_session_project"),
        ("project", "uq_project_organization"),
    ):
        op.drop_constraint(name, table, type_="unique")
