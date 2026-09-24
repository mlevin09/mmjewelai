"""Scoped repositories and atomic revision compare-and-swap."""

from datetime import datetime
from uuid import UUID

from jewelai_domain.models import DesignRevision
from jewelai_prompts import CompiledPrompt
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    DesignSessionRow,
    MessageRow,
    OrganizationRow,
    ProjectRow,
    PromptRevisionRow,
    QuestionEventRow,
    SpecificationRevisionRow,
)


class PersistenceError(RuntimeError):
    """Base error that is safe for the application layer to classify."""


class NotFoundError(PersistenceError):
    pass


class OwnershipMismatchError(NotFoundError):
    """Scoped lookup failed; intentionally indistinguishable from not found at HTTP boundary."""


class StaleRevisionError(PersistenceError):
    pass


class DuplicateRevisionError(PersistenceError):
    pass


class PersistenceRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_organization(
        self, organization_id: UUID, name: str, created_at: datetime
    ) -> OrganizationRow:
        with self._session_factory.begin() as db:
            row = OrganizationRow(organization_id=organization_id, name=name, created_at=created_at)
            db.add(row)
        return row

    def create_project(
        self,
        project_id: UUID,
        organization_id: UUID,
        name: str,
        created_at: datetime,
    ) -> ProjectRow:
        with self._session_factory.begin() as db:
            if db.get(OrganizationRow, organization_id) is None:
                raise NotFoundError("Organization not found")
            row = ProjectRow(
                project_id=project_id,
                organization_id=organization_id,
                name=name,
                created_at=created_at,
            )
            db.add(row)
        return row

    def get_project(self, project_id: UUID, organization_id: UUID) -> ProjectRow:
        with self._session_factory() as db:
            row = db.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == project_id,
                    ProjectRow.organization_id == organization_id,
                )
            )
            if row is None:
                raise OwnershipMismatchError("Project not found in organization scope")
            db.expunge(row)
            return row

    def create_design_session(
        self,
        row: DesignSessionRow,
        initial_revision: DesignRevision,
        *,
        organization_id: UUID,
    ) -> DesignSessionRow:
        revision = DesignRevision.model_validate(initial_revision)
        if row.current_revision_id != revision.revision_id:
            raise ValueError("Session current revision must match the initial revision")
        with self._session_factory.begin() as db:
            project = db.scalar(
                select(ProjectRow).where(
                    ProjectRow.project_id == row.project_id,
                    ProjectRow.organization_id == organization_id,
                )
            )
            if project is None:
                raise OwnershipMismatchError("Project not found in organization scope")
            db.add(row)
            db.add(self._revision_row(row.session_id, revision))
        return row

    def get_design_session(self, session_id: UUID, organization_id: UUID) -> DesignSessionRow:
        with self._session_factory() as db:
            row = db.scalar(self._scoped_session_query(session_id, organization_id))
            if row is None:
                raise OwnershipMismatchError("Session not found in organization scope")
            db.expunge(row)
            return row

    def get_current_revision(self, session_id: UUID, organization_id: UUID) -> DesignRevision:
        session = self.get_design_session(session_id, organization_id)
        return self.get_revision(session_id, session.current_revision_id, organization_id)

    def list_revisions(self, session_id: UUID, organization_id: UUID) -> tuple[DesignRevision, ...]:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            rows = db.scalars(
                select(SpecificationRevisionRow)
                .where(SpecificationRevisionRow.session_id == session_id)
                .order_by(SpecificationRevisionRow.revision_number)
            ).all()
            return tuple(self._domain_revision(row) for row in rows)

    def get_revision(
        self, session_id: UUID, revision_id: UUID, organization_id: UUID
    ) -> DesignRevision:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            row = db.scalar(
                select(SpecificationRevisionRow).where(
                    SpecificationRevisionRow.session_id == session_id,
                    SpecificationRevisionRow.revision_id == revision_id,
                )
            )
            if row is None:
                raise NotFoundError("Revision not found")
            return self._domain_revision(row)

    def append_revision_cas(
        self,
        session_id: UUID,
        organization_id: UUID,
        expected_revision_id: UUID,
        revision: DesignRevision,
    ) -> DesignRevision:
        revision = DesignRevision.model_validate(revision)
        if revision.parent_revision_id != expected_revision_id:
            raise ValueError("New revision parent must equal expected revision")
        try:
            with self._session_factory.begin() as db:
                parent = db.scalar(
                    select(SpecificationRevisionRow).where(
                        SpecificationRevisionRow.session_id == session_id,
                        SpecificationRevisionRow.revision_id == expected_revision_id,
                    )
                )
                if (
                    parent is None
                    or revision.design_id != parent.design_id
                    or revision.revision != parent.revision_number + 1
                    or revision.schema_version != parent.schema_version
                ):
                    raise DuplicateRevisionError(
                        "Revision must continue the stored design, schema, and sequence"
                    )
                scoped_projects = select(ProjectRow.project_id).where(
                    ProjectRow.organization_id == organization_id
                )
                result = db.execute(
                    update(DesignSessionRow)
                    .where(
                        DesignSessionRow.session_id == session_id,
                        DesignSessionRow.project_id.in_(scoped_projects),
                        DesignSessionRow.current_revision_id == expected_revision_id,
                    )
                    .values(
                        current_revision_id=revision.revision_id,
                        updated_at=revision.created_at,
                    )
                )
                if result.rowcount != 1:
                    raise StaleRevisionError(
                        "Current revision changed or session is outside organization scope"
                    )
                db.add(self._revision_row(session_id, revision))
        except IntegrityError as exc:
            raise DuplicateRevisionError(
                "Revision lineage violates a uniqueness constraint"
            ) from exc
        return revision

    def create_message(self, row: MessageRow, organization_id: UUID) -> MessageRow:
        with self._session_factory.begin() as db:
            scoped = db.scalar(self._scoped_session_query(row.session_id, organization_id))
            if scoped is None:
                raise OwnershipMismatchError("Session not found in organization scope")
            if row.actor != "user":
                raise ValueError("Parser Proposal v1 persists user messages only")
            db.add(row)
        return row

    def get_message(self, session_id: UUID, message_id: UUID, organization_id: UUID) -> MessageRow:
        with self._session_factory() as db:
            row = db.scalar(
                select(MessageRow)
                .join(DesignSessionRow, DesignSessionRow.session_id == MessageRow.session_id)
                .join(ProjectRow, ProjectRow.project_id == DesignSessionRow.project_id)
                .where(
                    MessageRow.message_id == message_id,
                    MessageRow.session_id == session_id,
                    ProjectRow.organization_id == organization_id,
                )
            )
            if row is None:
                raise OwnershipMismatchError("Message not found in session organization scope")
            db.expunge(row)
            return row

    def add_question_event(self, row: QuestionEventRow, organization_id: UUID) -> QuestionEventRow:
        with self._session_factory.begin() as db:
            scoped = db.scalar(self._scoped_session_query(row.session_id, organization_id))
            if scoped is None:
                raise OwnershipMismatchError("Session not found in organization scope")
            revision = db.scalar(
                select(SpecificationRevisionRow.revision_id).where(
                    SpecificationRevisionRow.session_id == row.session_id,
                    SpecificationRevisionRow.revision_id == row.specification_revision_id,
                )
            )
            if revision is None:
                raise NotFoundError("Question event revision does not belong to the session")
            db.add(row)
        return row

    def create_prompt_revision(
        self,
        row: PromptRevisionRow,
        compiled: CompiledPrompt,
        organization_id: UUID,
        expected_revision_id: UUID,
    ) -> PromptRevisionRow:
        compiled = CompiledPrompt.model_validate(compiled)
        self._validate_prompt_row(row, compiled)
        with self._session_factory.begin() as db:
            session = db.scalar(
                self._scoped_session_query(row.session_id, organization_id).with_for_update()
            )
            if session is None:
                raise OwnershipMismatchError("Session not found in organization scope")
            if session.current_revision_id != expected_revision_id:
                raise StaleRevisionError("Current revision changed during prompt compilation")
            revision = db.scalar(
                select(SpecificationRevisionRow.revision_id).where(
                    SpecificationRevisionRow.session_id == row.session_id,
                    SpecificationRevisionRow.revision_id == row.specification_revision_id,
                )
            )
            if revision is None:
                raise OwnershipMismatchError(
                    "Specification revision does not belong to prompt session"
                )
            db.add(row)
        return row

    def get_prompt_revision(
        self,
        session_id: UUID,
        prompt_revision_id: UUID,
        organization_id: UUID,
    ) -> tuple[PromptRevisionRow, CompiledPrompt]:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            row = db.scalar(
                select(PromptRevisionRow).where(
                    PromptRevisionRow.session_id == session_id,
                    PromptRevisionRow.prompt_revision_id == prompt_revision_id,
                )
            )
            if row is None:
                raise NotFoundError("Prompt revision not found")
            compiled = self._compiled_prompt(row)
            db.expunge(row)
            return row, compiled

    def list_prompt_revisions(
        self, session_id: UUID, organization_id: UUID
    ) -> tuple[tuple[PromptRevisionRow, CompiledPrompt], ...]:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            rows = db.scalars(
                select(PromptRevisionRow)
                .where(PromptRevisionRow.session_id == session_id)
                .order_by(PromptRevisionRow.created_at, PromptRevisionRow.prompt_revision_id)
            ).all()
            result = tuple((row, self._compiled_prompt(row)) for row in rows)
            for row in rows:
                db.expunge(row)
            return result

    def list_question_events(
        self, session_id: UUID, organization_id: UUID
    ) -> tuple[QuestionEventRow, ...]:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            rows = db.scalars(
                select(QuestionEventRow)
                .where(QuestionEventRow.session_id == session_id)
                .order_by(QuestionEventRow.created_at, QuestionEventRow.event_id)
            ).all()
            for row in rows:
                db.expunge(row)
            return tuple(rows)

    @staticmethod
    def _revision_row(session_id: UUID, revision: DesignRevision) -> SpecificationRevisionRow:
        payload = revision.model_dump(mode="json")
        return SpecificationRevisionRow(
            revision_id=revision.revision_id,
            session_id=session_id,
            design_id=revision.design_id,
            revision_number=revision.revision,
            parent_revision_id=revision.parent_revision_id,
            schema_version=revision.schema_version,
            created_at=revision.created_at,
            event_data=revision.event.model_dump(mode="json"),
            snapshot=payload,
        )

    @staticmethod
    def _domain_revision(row: SpecificationRevisionRow) -> DesignRevision:
        return DesignRevision.model_validate(row.snapshot)

    @staticmethod
    def _validate_prompt_row(row: PromptRevisionRow, compiled: CompiledPrompt) -> None:
        expected = (
            row.specification_revision_id,
            row.prompt_schema_version,
            row.compiler_version,
            row.template_id,
            row.template_version,
            row.template_artifact_version,
            row.compiled_text,
            row.content_hash,
        )
        actual = (
            compiled.specification_revision_id,
            compiled.schema_version,
            compiled.compiler_version,
            compiled.template_id,
            compiled.template_version,
            compiled.template_artifact_version,
            compiled.prompt_text,
            compiled.content_hash,
        )
        if expected != actual or row.structured_payload != compiled.model_dump(mode="json"):
            raise ValueError("Prompt revision relational metadata does not match compiled payload")

    @classmethod
    def _compiled_prompt(cls, row: PromptRevisionRow) -> CompiledPrompt:
        compiled = CompiledPrompt.model_validate(row.structured_payload)
        cls._validate_prompt_row(row, compiled)
        return compiled

    @staticmethod
    def _scoped_session_query(session_id: UUID, organization_id: UUID):
        return (
            select(DesignSessionRow)
            .join(ProjectRow, ProjectRow.project_id == DesignSessionRow.project_id)
            .where(
                DesignSessionRow.session_id == session_id,
                ProjectRow.organization_id == organization_id,
            )
        )
