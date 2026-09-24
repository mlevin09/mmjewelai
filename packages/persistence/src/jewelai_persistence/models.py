"""PostgreSQL-compatible relational lineage and JSON snapshot storage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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


class ProjectRow(Base):
    __tablename__ = "project"

    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organization.organization_id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DesignSessionRow(Base):
    __tablename__ = "design_session"

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


class SpecificationRevisionRow(Base):
    __tablename__ = "specification_revision"
    __table_args__ = (
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


class GenerationRunRow(Base):
    __tablename__ = "generation_run"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_generation_run_attempt_positive"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_generation_run_status",
        ),
        Index("ix_generation_run_session_created", "session_id", "created_at"),
    )

    generation_run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
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
