"""PostgreSQL-compatible relational lineage and JSON snapshot storage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OrganizationRow(Base):
    __tablename__ = "organization"

    organization_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthPrincipalRow(Base):
    __tablename__ = "auth_principal"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_auth_principal_issuer_subject"),
    )

    principal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrganizationMembershipRow(Base):
    __tablename__ = "organization_membership"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_membership_role"),
        Index("ix_membership_principal", "principal_id"),
        Index("ix_membership_organization", "organization_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), primary_key=True
    )
    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_principal.principal_id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectRow(Base):
    __tablename__ = "project"
    __table_args__ = (
        UniqueConstraint("project_id", "organization_id", name="uq_project_organization"),
    )

    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DesignSessionRow(Base):
    __tablename__ = "design_session"
    __table_args__ = (
        UniqueConstraint("session_id", "project_id", name="uq_design_session_project"),
        CheckConstraint(
            "(knowledge_package_id IS NULL AND knowledge_artifact_version IS NULL "
            "AND knowledge_runtime_sha256 IS NULL "
            "AND knowledge_validation_report_sha256 IS NULL) OR "
            "(knowledge_package_id IS NOT NULL AND knowledge_artifact_version IS NOT NULL "
            "AND knowledge_runtime_sha256 IS NOT NULL "
            "AND knowledge_validation_report_sha256 IS NOT NULL)",
            name="ck_design_session_knowledge_pin_complete",
        ),
    )

    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"), index=True
    )
    role_id: Mapped[str] = mapped_column(String(80))
    locale: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_revision_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    design_schema_version: Mapped[str] = mapped_column(String(32))
    role_artifact_version: Mapped[str] = mapped_column(String(32))
    dictionary_artifact_version: Mapped[str] = mapped_column(String(32))
    question_artifact_version: Mapped[str] = mapped_column(String(32))
    rules_artifact_version: Mapped[str] = mapped_column(String(32))
    prompt_artifact_version: Mapped[str] = mapped_column(String(32))
    knowledge_package_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    knowledge_artifact_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    knowledge_runtime_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    knowledge_validation_report_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )


class SpecificationRevisionRow(Base):
    __tablename__ = "specification_revision"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "revision_id", "design_id", name="uq_revision_session_design"
        ),
        UniqueConstraint("session_id", "revision_number", name="uq_revision_session_number"),
        UniqueConstraint("session_id", "parent_revision_id", name="uq_revision_session_parent"),
        Index("ix_revision_session_created", "session_id", "created_at"),
    )

    revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    design_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    parent_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), nullable=True
    )
    schema_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_data: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)


class MessageRow(Base):
    __tablename__ = "message"
    __table_args__ = (Index("ix_message_session_created", "session_id", "created_at"),)

    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    actor: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuestionEventRow(Base):
    __tablename__ = "question_event"
    __table_args__ = (Index("ix_question_event_session_created", "session_id", "created_at"),)

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    specification_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    semantic_question_id: Mapped[str] = mapped_column(String(100))
    rules_artifact_version: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[str] = mapped_column(String(100))
    rule_version: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(120))
    concrete_target: Mapped[str | None] = mapped_column(String(240), nullable=True)
    decision: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(100))
    trace_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PromptRevisionRow(Base):
    __tablename__ = "prompt_revision"
    __table_args__ = (Index("ix_prompt_revision_session_created", "session_id", "created_at"),)

    prompt_revision_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    specification_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    prompt_schema_version: Mapped[str] = mapped_column(String(32))
    compiler_version: Mapped[str] = mapped_column(String(32))
    template_id: Mapped[str] = mapped_column(String(80))
    template_version: Mapped[str] = mapped_column(String(32))
    template_artifact_version: Mapped[str] = mapped_column(String(32))
    compiled_text: Mapped[str] = mapped_column(String)
    structured_payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnrichmentCycleRow(Base):
    __tablename__ = "enrichment_cycle"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "enrichment_cycle_id",
            "cycle_number",
            "specification_revision_id",
            name="uq_cycle_preparation_binding",
        ),
        CheckConstraint("cycle_number >= 1", name="ck_enrichment_cycle_number_positive"),
        UniqueConstraint("session_id", "cycle_number", name="uq_enrichment_cycle_session_number"),
        Index("ix_enrichment_cycle_session_created", "session_id", "created_at"),
    )

    enrichment_cycle_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    cycle_number: Mapped[int] = mapped_column(Integer)
    specification_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    knowledge_package_id: Mapped[str] = mapped_column(String(200))
    knowledge_artifact_version: Mapped[str] = mapped_column(String(32))
    knowledge_runtime_sha256: Mapped[str] = mapped_column(String(64))
    knowledge_validation_report_sha256: Mapped[str] = mapped_column(String(64))
    enrichment_version: Mapped[str] = mapped_column(String(32))
    result_payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenerationPreparationRow(Base):
    __tablename__ = "generation_preparation"
    __table_args__ = (
        *(
            CheckConstraint(f"{field} ~ '^[0-9a-f]{{64}}$'", name=f"ck_preparation_{field}").ddl_if(
                dialect="postgresql"
            )
            for field in (
                "enrichment_result_hash",
                "source_handoff_hash",
                "source_bytes_sha256",
                "gate_evidence_hash",
                "rendering_hash",
                "artifact_hash",
            )
        ),
        UniqueConstraint(
            "preparation_id", "organization_id", "session_id", name="uq_preparation_scope"
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["project.project_id", "project.organization_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "project_id"],
            ["design_session.session_id", "design_session.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "product_state_revision_id", "design_id"],
            [
                "specification_revision.session_id",
                "specification_revision.revision_id",
                "specification_revision.design_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "session_id",
                "enrichment_cycle_id",
                "enrichment_cycle_number",
                "product_state_revision_id",
            ],
            [
                "enrichment_cycle.session_id",
                "enrichment_cycle.enrichment_cycle_id",
                "enrichment_cycle.cycle_number",
                "enrichment_cycle.specification_revision_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("schema_version = '1.0.0'", name="ck_preparation_version"),
        CheckConstraint("length(artifact_bytes) <= 2097152", name="ck_preparation_artifact_size"),
        Index("ix_preparation_session_created", "session_id", "created_at"),
    )
    preparation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid)
    design_id: Mapped[UUID] = mapped_column(Uuid)
    product_state_revision_id: Mapped[UUID] = mapped_column(Uuid)
    enrichment_cycle_id: Mapped[UUID] = mapped_column(Uuid)
    enrichment_cycle_number: Mapped[int] = mapped_column(Integer)
    enrichment_result_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))
    source_handoff_hash: Mapped[str] = mapped_column(String(64))
    source_bytes_sha256: Mapped[str] = mapped_column(String(64))
    gate_evidence_hash: Mapped[str] = mapped_column(String(64))
    rendering_hash: Mapped[str] = mapped_column(String(64))
    artifact_hash: Mapped[str] = mapped_column(String(64))
    source_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    artifact_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    artifact_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenerationCommandRow(Base):
    __tablename__ = "generation_command"
    __table_args__ = (
        *(
            CheckConstraint(
                f"{field} ~ '^[0-9a-f]{{64}}$'", name=f"ck_generation_command_{field}"
            ).ddl_if(dialect="postgresql")
            for field in ("request_hash", "response_hash")
        ),
        ForeignKeyConstraint(
            ["preparation_id", "organization_id", "session_id"],
            [
                "generation_preparation.preparation_id",
                "generation_preparation.organization_id",
                "generation_preparation.session_id",
            ],
            ondelete="RESTRICT",
        ),
    )
    organization_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    command: Mapped[str] = mapped_column(String(80), primary_key=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    preparation_id: Mapped[UUID] = mapped_column(Uuid)
    response_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    response_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClarificationPlanRow(Base):
    __tablename__ = "clarification_plan"
    __table_args__ = (
        UniqueConstraint("enrichment_cycle_id", name="uq_clarification_plan_enrichment_cycle"),
        Index("ix_clarification_plan_session_created", "session_id", "created_at"),
        Index(
            "ix_clarification_plan_session_revision",
            "session_id",
            "specification_revision_id",
        ),
    )

    clarification_plan_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    enrichment_cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrichment_cycle.enrichment_cycle_id", ondelete="RESTRICT"), index=True
    )
    specification_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    plan_version: Mapped[str] = mapped_column(String(32))
    knowledge_package_id: Mapped[str] = mapped_column(String(200))
    knowledge_artifact_version: Mapped[str] = mapped_column(String(32))
    knowledge_runtime_sha256: Mapped[str] = mapped_column(String(64))
    knowledge_validation_report_sha256: Mapped[str] = mapped_column(String(64))
    dictionary_artifact_version: Mapped[str] = mapped_column(String(32))
    question_artifact_version: Mapped[str] = mapped_column(String(32))
    rules_artifact_version: Mapped[str] = mapped_column(String(32))
    plan_payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClarificationAnswerRow(Base):
    __tablename__ = "clarification_answer"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "plan_content_hash",
            "clarification_id",
            name="uq_clarification_answer_question",
        ),
        Index("ix_clarification_answer_session_created", "session_id", "created_at"),
    )

    answer_record_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    clarification_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("clarification_plan.clarification_plan_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    plan_content_hash: Mapped[str] = mapped_column(String(64))
    clarification_id: Mapped[str] = mapped_column(String(200))
    previous_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    new_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(32))
    answer_hash: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_package_id: Mapped[str] = mapped_column(String(200))
    knowledge_artifact_version: Mapped[str] = mapped_column(String(32))
    knowledge_runtime_sha256: Mapped[str] = mapped_column(String(64))
    knowledge_validation_report_sha256: Mapped[str] = mapped_column(String(64))
    question_artifact_version: Mapped[str] = mapped_column(String(32))
    rules_artifact_version: Mapped[str] = mapped_column(String(32))
    result_payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserCorrectionRow(Base):
    __tablename__ = "user_correction"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "source_identity_hash",
            name="uq_user_correction_source",
        ),
        UniqueConstraint("next_enrichment_cycle_id", name="uq_user_correction_next_cycle"),
        Index("ix_user_correction_session_created", "session_id", "created_at"),
    )

    correction_record_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(32))
    source_message_id: Mapped[str] = mapped_column(String(2000))
    source_identity_hash: Mapped[str] = mapped_column(String(64))
    correction_text: Mapped[str] = mapped_column(String(2000))
    previous_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    new_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    previous_enrichment_cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrichment_cycle.enrichment_cycle_id", ondelete="RESTRICT"), index=True
    )
    next_enrichment_cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrichment_cycle.enrichment_cycle_id", ondelete="RESTRICT"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(100))
    semantic_hash: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_package_id: Mapped[str] = mapped_column(String(200))
    knowledge_artifact_version: Mapped[str] = mapped_column(String(32))
    knowledge_runtime_sha256: Mapped[str] = mapped_column(String(64))
    knowledge_validation_report_sha256: Mapped[str] = mapped_column(String(64))
    dictionary_artifact_version: Mapped[str] = mapped_column(String(32))
    prompt_template_artifact_version: Mapped[str] = mapped_column(String(32))
    result_payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IterativeEditRow(Base):
    __tablename__ = "iterative_edit"
    __table_args__ = (Index("ix_iterative_edit_session_created", "session_id", "created_at"),)

    edit_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset.asset_id", ondelete="RESTRICT"), index=True
    )
    starting_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"), index=True
    )
    initial_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("message.message_id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VisualizationIterationRow(Base):
    __tablename__ = "visualization_iteration"
    __table_args__ = (
        Index("ix_visualization_iteration_session_created", "session_id", "created_at"),
    )

    iteration_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    iterative_edit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "iterative_edit.edit_id",
            name="fk_visualization_iteration_iterative_edit",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        unique=True,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    prompt_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_revision.prompt_revision_id", ondelete="RESTRICT"), index=True
    )
    prompt_content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenerationRunRow(Base):
    __tablename__ = "generation_run"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_generation_run_attempt_positive"),
        CheckConstraint(
            "(attempt = 1 AND parent_generation_run_id IS NULL) OR "
            "(attempt > 1 AND parent_generation_run_id IS NOT NULL)",
            name="ck_generation_run_retry_lineage",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_generation_run_status",
        ),
        Index("ix_generation_run_session_created", "session_id", "created_at"),
        Index("ix_generation_run_status_started", "status", "started_at"),
        Index(
            "ix_generation_run_reconcile_scan",
            "status",
            "assets_reconciled_at",
            "completed_at",
        ),
        Index(
            "ix_generation_run_cleanup_scan",
            "status",
            "orphan_cleanup_completed_at",
            "completed_at",
        ),
        UniqueConstraint("parent_generation_run_id", name="uq_generation_run_direct_retry_child"),
    )

    generation_run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    iteration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("visualization_iteration.iteration_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    prompt_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_revision.prompt_revision_id", ondelete="RESTRICT"), index=True
    )
    prompt_content_hash: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(String(100))
    profile_version: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    configuration: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    parent_generation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("generation_run.generation_run_id", ondelete="RESTRICT"), nullable=True
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assets_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    orphan_cleanup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class VisualizationSelectionRow(Base):
    __tablename__ = "visualization_selection"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('selected', 'rejected')", name="ck_visual_selection_decision"
        ),
        CheckConstraint(
            "(decision = 'selected' AND asset_id IS NOT NULL) OR "
            "(decision = 'rejected' AND asset_id IS NULL)",
            name="ck_visual_selection_asset",
        ),
        Index("ix_visual_selection_session_created", "session_id", "created_at"),
    )

    iteration_id: Mapped[UUID] = mapped_column(
        ForeignKey("visualization_iteration.iteration_id", ondelete="RESTRICT"), primary_key=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset.asset_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    selected_by_principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_principal.principal_id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenerationDispatchOutboxRow(Base):
    __tablename__ = "generation_dispatch_outbox"
    __table_args__ = (Index("ix_generation_dispatch_pending", "published_at", "created_at"),)

    generation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_run.generation_run_id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetRow(Base):
    __tablename__ = "asset"
    __table_args__ = (
        CheckConstraint("kind IN ('reference', 'generated')", name="ck_asset_kind"),
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_asset_status"),
        CheckConstraint("byte_size > 0", name="ck_asset_byte_size_positive"),
        CheckConstraint(
            "generation_output_ordinal IS NULL OR generation_output_ordinal BETWEEN 1 AND 4",
            name="ck_asset_generation_ordinal",
        ),
        CheckConstraint(
            "parent_asset_id IS NULL OR parent_asset_id != asset_id",
            name="ck_asset_parent",
        ),
        CheckConstraint(
            "(kind = 'reference' AND generation_run_id IS NULL "
            "AND generation_output_ordinal IS NULL AND provider_output_id IS NULL) OR "
            "(kind = 'generated' AND generation_run_id IS NOT NULL "
            "AND generation_output_ordinal IS NOT NULL)",
            name="ck_asset_kind_lineage",
        ),
        CheckConstraint(
            "(status = 'pending' AND ready_at IS NULL AND failed_at IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL AND failed_at IS NULL "
            "AND error_code IS NULL AND error_detail IS NULL) OR "
            "(status = 'failed' AND ready_at IS NULL AND failed_at IS NOT NULL "
            "AND error_code IS NOT NULL AND error_detail IS NOT NULL)",
            name="ck_asset_lifecycle",
        ),
        UniqueConstraint("object_key", name="uq_asset_object_key"),
        UniqueConstraint(
            "generation_run_id",
            "generation_output_ordinal",
            name="uq_asset_generation_output",
        ),
        Index("ix_asset_session_created", "session_id", "created_at"),
    )

    asset_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    object_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    generation_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("generation_run.generation_run_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    generation_output_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_output_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    parent_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset.asset_id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ReferenceBindingRow(Base):
    __tablename__ = "reference_binding"
    __table_args__ = (
        Index("ix_reference_binding_session_created", "session_id", "created_at"),
        Index("ix_reference_binding_asset", "asset_id"),
    )

    binding_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("asset.asset_id", ondelete="RESTRICT"))
    contract_version: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VisualizationVerificationRow(Base):
    __tablename__ = "visualization_verification"
    __table_args__ = (
        Index("ix_visualization_verification_session_created", "session_id", "created_at"),
        Index("ix_visualization_verification_generation_run", "generation_run_id"),
        Index("ix_visualization_verification_asset", "asset_id"),
    )

    verification_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("design_session.session_id", ondelete="RESTRICT"), index=True
    )
    generation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_run.generation_run_id", ondelete="RESTRICT")
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset.asset_id", ondelete="RESTRICT"), nullable=True
    )
    design_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("specification_revision.revision_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    previous_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset.asset_id", ondelete="RESTRICT"), nullable=True
    )
    contract_version: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
