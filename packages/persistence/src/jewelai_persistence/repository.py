"""Scoped repositories and atomic revision compare-and-swap."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from jewelai_assets import (
    Asset,
    AssetConflictError,
    AssetErrorCode,
    AssetLineageError,
    AssetStatus,
    validate_asset_object_key,
)
from jewelai_auth import (
    LastOwnerError,
    MembershipConflictError,
    MembershipNotFoundError,
    MembershipRole,
    VerifiedIdentity,
)
from jewelai_domain.models import DesignRevision
from jewelai_generation_queue import GenerationTaskEnvelope, PendingGenerationDispatch
from jewelai_model_gateway import (
    GenerationErrorCode,
    GenerationRequest,
    GenerationResult,
    GenerationRun,
    GenerationStatus,
    validate_generation_result,
)
from jewelai_prompts import CompiledPrompt
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    AssetRow,
    AuthPrincipalRow,
    DesignSessionRow,
    GenerationDispatchOutboxRow,
    GenerationRunRow,
    MessageRow,
    OrganizationMembershipRow,
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


class GenerationStateConflictError(PersistenceError):
    pass


class GenerationRetryNotAllowedError(GenerationStateConflictError):
    pass


@dataclass(frozen=True)
class StaleGenerationRunCandidate:
    generation_run_id: UUID
    session_id: UUID
    organization_id: UUID
    started_at: datetime


@dataclass(frozen=True)
class GenerationRetryCreation:
    run: GenerationRun
    dispatch: PendingGenerationDispatch | None
    created: bool


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

    def get_or_create_principal(
        self,
        identity: VerifiedIdentity,
        principal_id: UUID,
        now: datetime,
    ) -> AuthPrincipalRow:
        identity = VerifiedIdentity.model_validate(identity)
        for attempt in range(2):
            try:
                with self._session_factory.begin() as db:
                    row = db.scalar(
                        select(AuthPrincipalRow).where(
                            AuthPrincipalRow.issuer == identity.issuer,
                            AuthPrincipalRow.subject == identity.subject,
                        )
                    )
                    if row is None:
                        row = AuthPrincipalRow(
                            principal_id=principal_id,
                            issuer=identity.issuer,
                            subject=identity.subject,
                            email=identity.email,
                            display_name=identity.display_name,
                            created_at=now,
                            updated_at=now,
                        )
                        db.add(row)
                    elif row.email != identity.email or row.display_name != identity.display_name:
                        row.email = identity.email
                        row.display_name = identity.display_name
                        row.updated_at = now
                return row
            except IntegrityError:
                if attempt:
                    raise
        raise AssertionError("Principal resolution retry was not reached")

    def get_principal(self, principal_id: UUID) -> AuthPrincipalRow:
        with self._session_factory() as db:
            row = db.get(AuthPrincipalRow, principal_id)
            if row is None:
                raise MembershipNotFoundError("Principal not found")
            db.expunge(row)
            return row

    def create_organization_with_owner(
        self,
        organization_id: UUID,
        name: str,
        principal_id: UUID,
        created_at: datetime,
    ) -> OrganizationRow:
        with self._session_factory.begin() as db:
            if db.get(AuthPrincipalRow, principal_id) is None:
                raise MembershipNotFoundError("Principal not found")
            row = OrganizationRow(organization_id=organization_id, name=name, created_at=created_at)
            db.add(row)
            db.flush()
            db.add(
                OrganizationMembershipRow(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    role=MembershipRole.OWNER.value,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        return row

    def get_membership(
        self, organization_id: UUID, principal_id: UUID
    ) -> OrganizationMembershipRow:
        with self._session_factory() as db:
            row = db.get(OrganizationMembershipRow, (organization_id, principal_id))
            if row is None:
                raise MembershipNotFoundError("Organization membership not found")
            db.expunge(row)
            return row

    def list_principal_memberships(
        self, principal_id: UUID
    ) -> tuple[tuple[OrganizationMembershipRow, OrganizationRow], ...]:
        with self._session_factory() as db:
            rows = db.execute(
                select(OrganizationMembershipRow, OrganizationRow)
                .join(
                    OrganizationRow,
                    OrganizationRow.organization_id == OrganizationMembershipRow.organization_id,
                )
                .where(OrganizationMembershipRow.principal_id == principal_id)
                .order_by(
                    OrganizationMembershipRow.created_at,
                    OrganizationMembershipRow.organization_id,
                )
            ).all()
            for membership, organization in rows:
                db.expunge(membership)
                db.expunge(organization)
            return tuple(rows)

    def list_organization_memberships(
        self, organization_id: UUID
    ) -> tuple[tuple[OrganizationMembershipRow, AuthPrincipalRow], ...]:
        with self._session_factory() as db:
            if db.get(OrganizationRow, organization_id) is None:
                raise MembershipNotFoundError("Organization not found")
            rows = db.execute(
                select(OrganizationMembershipRow, AuthPrincipalRow)
                .join(
                    AuthPrincipalRow,
                    AuthPrincipalRow.principal_id == OrganizationMembershipRow.principal_id,
                )
                .where(OrganizationMembershipRow.organization_id == organization_id)
                .order_by(
                    OrganizationMembershipRow.created_at,
                    OrganizationMembershipRow.principal_id,
                )
            ).all()
            for membership, principal in rows:
                db.expunge(membership)
                db.expunge(principal)
            return tuple(rows)

    def add_membership(
        self,
        organization_id: UUID,
        principal_id: UUID,
        role: MembershipRole,
        now: datetime,
    ) -> OrganizationMembershipRow:
        try:
            with self._session_factory.begin() as db:
                if db.get(OrganizationRow, organization_id) is None:
                    raise MembershipNotFoundError("Organization not found")
                if db.get(AuthPrincipalRow, principal_id) is None:
                    raise MembershipNotFoundError("Principal not found")
                row = OrganizationMembershipRow(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    role=MembershipRole(role).value,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
            return row
        except IntegrityError as exc:
            raise MembershipConflictError("Principal is already an organization member") from exc

    def update_membership_role(
        self,
        organization_id: UUID,
        principal_id: UUID,
        role: MembershipRole,
        now: datetime,
    ) -> OrganizationMembershipRow:
        with self._session_factory.begin() as db:
            organization = db.scalar(
                select(OrganizationRow)
                .where(OrganizationRow.organization_id == organization_id)
                .with_for_update()
            )
            if organization is None:
                raise MembershipNotFoundError("Organization not found")
            row = db.get(OrganizationMembershipRow, (organization_id, principal_id))
            if row is None:
                raise MembershipNotFoundError("Organization membership not found")
            target = MembershipRole(role)
            if row.role == MembershipRole.OWNER.value and target is not MembershipRole.OWNER:
                self._require_another_owner(db, organization_id, principal_id)
            row.role = target.value
            row.updated_at = now
        return row

    def delete_membership(self, organization_id: UUID, principal_id: UUID) -> None:
        with self._session_factory.begin() as db:
            organization = db.scalar(
                select(OrganizationRow)
                .where(OrganizationRow.organization_id == organization_id)
                .with_for_update()
            )
            if organization is None:
                raise MembershipNotFoundError("Organization not found")
            row = db.get(OrganizationMembershipRow, (organization_id, principal_id))
            if row is None:
                raise MembershipNotFoundError("Organization membership not found")
            if row.role == MembershipRole.OWNER.value:
                self._require_another_owner(db, organization_id, principal_id)
            db.delete(row)

    @staticmethod
    def _require_another_owner(db: Session, organization_id: UUID, principal_id: UUID) -> None:
        count = db.scalar(
            select(func.count())
            .select_from(OrganizationMembershipRow)
            .where(
                OrganizationMembershipRow.organization_id == organization_id,
                OrganizationMembershipRow.role == MembershipRole.OWNER.value,
                OrganizationMembershipRow.principal_id != principal_id,
            )
        )
        if not count:
            raise LastOwnerError("Organization must retain at least one owner")

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

    def create_generation_run(self, run: GenerationRun, organization_id: UUID) -> GenerationRun:
        run = GenerationRun.model_validate(run)
        with self._session_factory.begin() as db:
            self._add_generation_run(db, run, organization_id)
        return run

    def create_generation_run_with_dispatch(
        self, run: GenerationRun, organization_id: UUID
    ) -> PendingGenerationDispatch:
        """Atomically persist an initial run and its one durable dispatch intent."""
        run = GenerationRun.model_validate(run)
        with self._session_factory.begin() as db:
            session = self._add_generation_run(db, run, organization_id)
            db.flush()
            db.add(
                GenerationDispatchOutboxRow(
                    generation_run_id=run.generation_run_id,
                    created_at=run.created_at,
                    published_at=None,
                )
            )
            task = GenerationTaskEnvelope(
                generation_run_id=run.generation_run_id,
                session_id=session.session_id,
                organization_id=organization_id,
            )
        return PendingGenerationDispatch(task=task, created_at=run.created_at)

    def list_pending_generation_dispatches(
        self, batch_size: int
    ) -> tuple[PendingGenerationDispatch, ...]:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100")
        with self._session_factory() as db:
            rows = db.execute(
                select(
                    GenerationDispatchOutboxRow,
                    GenerationRunRow.session_id,
                    ProjectRow.organization_id,
                )
                .join(GenerationRunRow)
                .join(DesignSessionRow, DesignSessionRow.session_id == GenerationRunRow.session_id)
                .join(ProjectRow, ProjectRow.project_id == DesignSessionRow.project_id)
                .where(GenerationDispatchOutboxRow.published_at.is_(None))
                .order_by(
                    GenerationDispatchOutboxRow.created_at,
                    GenerationDispatchOutboxRow.generation_run_id,
                )
                .limit(batch_size)
            ).all()
            return tuple(
                PendingGenerationDispatch(
                    task=GenerationTaskEnvelope(
                        generation_run_id=outbox.generation_run_id,
                        session_id=session_id,
                        organization_id=organization_id,
                    ),
                    created_at=outbox.created_at,
                )
                for outbox, session_id, organization_id in rows
            )

    def mark_generation_dispatch_published(
        self, generation_run_id: UUID, published_at: datetime
    ) -> datetime:
        with self._session_factory.begin() as db:
            row = db.get(GenerationDispatchOutboxRow, generation_run_id)
            if row is None:
                raise NotFoundError("Generation dispatch not found")
            if row.published_at is None:
                row.published_at = published_at
            return row.published_at

    def get_generation_dispatch(self, generation_run_id: UUID) -> GenerationDispatchOutboxRow:
        with self._session_factory() as db:
            row = db.get(GenerationDispatchOutboxRow, generation_run_id)
            if row is None:
                raise NotFoundError("Generation dispatch not found")
            db.expunge(row)
            return row

    def list_stale_running_generation_runs(
        self, cutoff: datetime, batch_size: int
    ) -> tuple[StaleGenerationRunCandidate, ...]:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100")
        with self._session_factory() as db:
            rows = db.execute(
                select(
                    GenerationRunRow.generation_run_id,
                    GenerationRunRow.session_id,
                    ProjectRow.organization_id,
                    GenerationRunRow.started_at,
                )
                .join(DesignSessionRow, DesignSessionRow.session_id == GenerationRunRow.session_id)
                .join(ProjectRow, ProjectRow.project_id == DesignSessionRow.project_id)
                .where(
                    GenerationRunRow.status == GenerationStatus.RUNNING.value,
                    GenerationRunRow.started_at.is_not(None),
                    GenerationRunRow.started_at <= cutoff,
                )
                .order_by(GenerationRunRow.started_at, GenerationRunRow.generation_run_id)
                .limit(batch_size)
            ).all()
            return tuple(
                StaleGenerationRunCandidate(
                    generation_run_id=generation_run_id,
                    session_id=session_id,
                    organization_id=organization_id,
                    started_at=self._utc(started_at),
                )
                for generation_run_id, session_id, organization_id, started_at in rows
            )

    def fail_stale_generation_run(
        self,
        generation_run_id: UUID,
        *,
        cutoff: datetime,
        completed_at: datetime,
    ) -> bool:
        """Atomically classify one sufficiently old RUNNING run as terminal FAILED."""
        with self._session_factory.begin() as db:
            result = db.execute(
                update(GenerationRunRow)
                .where(
                    GenerationRunRow.generation_run_id == generation_run_id,
                    GenerationRunRow.status == GenerationStatus.RUNNING.value,
                    GenerationRunRow.started_at.is_not(None),
                    GenerationRunRow.started_at <= cutoff,
                )
                .values(
                    status=GenerationStatus.FAILED.value,
                    error_code=GenerationErrorCode.EXECUTION_STALE.value,
                    error_detail="Generation execution exceeded the recovery deadline",
                    completed_at=completed_at,
                )
            )
            return result.rowcount == 1

    def create_generation_retry_with_dispatch(
        self,
        *,
        parent_generation_run_id: UUID,
        session_id: UUID,
        organization_id: UUID,
        new_generation_run_id: UUID,
        created_at: datetime,
    ) -> GenerationRetryCreation:
        """Idempotently create one exact-input retry child and durable dispatch."""
        with self._session_factory.begin() as db:
            parent = db.scalar(
                select(GenerationRunRow)
                .where(
                    GenerationRunRow.generation_run_id == parent_generation_run_id,
                    GenerationRunRow.session_id == session_id,
                    GenerationRunRow.session_id.in_(self._scoped_session_ids(organization_id)),
                )
                .with_for_update()
            )
            if parent is None:
                raise OwnershipMismatchError("Generation run not found in organization scope")
            if parent.status != GenerationStatus.FAILED.value:
                raise GenerationRetryNotAllowedError("Generation run is not eligible for retry")

            child = db.scalar(
                select(GenerationRunRow).where(
                    GenerationRunRow.parent_generation_run_id == parent_generation_run_id
                )
            )
            created = child is None
            if child is None:
                child_run = GenerationRun(
                    generation_run_id=new_generation_run_id,
                    session_id=parent.session_id,
                    prompt_revision_id=parent.prompt_revision_id,
                    prompt_content_hash=parent.prompt_content_hash,
                    profile_id=parent.profile_id,
                    profile_version=parent.profile_version,
                    provider=parent.provider,
                    model=parent.model,
                    configuration=parent.configuration,
                    status=GenerationStatus.PENDING,
                    attempt=parent.attempt + 1,
                    parent_generation_run_id=parent.generation_run_id,
                    created_at=created_at,
                )
                child = self._generation_row(child_run)
                db.add(child)
                db.flush()
                outbox = GenerationDispatchOutboxRow(
                    generation_run_id=child.generation_run_id,
                    created_at=created_at,
                    published_at=None,
                )
                db.add(outbox)
            else:
                child_run = self._generation_run(child)
                outbox = db.get(GenerationDispatchOutboxRow, child.generation_run_id)
                if outbox is None:
                    raise GenerationStateConflictError("Retry generation dispatch is missing")

            dispatch = None
            if outbox.published_at is None:
                dispatch = PendingGenerationDispatch(
                    task=GenerationTaskEnvelope(
                        generation_run_id=child.generation_run_id,
                        session_id=child.session_id,
                        organization_id=organization_id,
                    ),
                    created_at=self._utc(outbox.created_at),
                )
            return GenerationRetryCreation(run=child_run, dispatch=dispatch, created=created)

    def get_generation_run(
        self, session_id: UUID, generation_run_id: UUID, organization_id: UUID
    ) -> GenerationRun:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            row = db.scalar(
                select(GenerationRunRow).where(
                    GenerationRunRow.session_id == session_id,
                    GenerationRunRow.generation_run_id == generation_run_id,
                )
            )
            if row is None:
                raise NotFoundError("Generation run not found")
            return self._generation_run(row)

    def list_generation_runs(
        self, session_id: UUID, organization_id: UUID
    ) -> tuple[GenerationRun, ...]:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            rows = db.scalars(
                select(GenerationRunRow)
                .where(GenerationRunRow.session_id == session_id)
                .order_by(GenerationRunRow.created_at, GenerationRunRow.generation_run_id)
            ).all()
            return tuple(self._generation_run(row) for row in rows)

    def find_asset(self, asset_id: UUID, organization_id: UUID) -> Asset | None:
        with self._session_factory() as db:
            row = db.scalar(
                select(AssetRow).where(
                    AssetRow.asset_id == asset_id,
                    AssetRow.organization_id == organization_id,
                    AssetRow.session_id.in_(self._scoped_session_ids(organization_id)),
                )
            )
            return self._asset(row) if row is not None else None

    def get_asset(self, session_id: UUID, asset_id: UUID, organization_id: UUID) -> Asset:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            row = db.scalar(
                select(AssetRow).where(
                    AssetRow.asset_id == asset_id,
                    AssetRow.session_id == session_id,
                    AssetRow.organization_id == organization_id,
                )
            )
            if row is None:
                raise OwnershipMismatchError("Asset not found in session organization scope")
            return self._asset(row)

    def list_assets(self, session_id: UUID, organization_id: UUID) -> tuple[Asset, ...]:
        self.get_design_session(session_id, organization_id)
        with self._session_factory() as db:
            rows = db.scalars(
                select(AssetRow)
                .where(
                    AssetRow.session_id == session_id,
                    AssetRow.organization_id == organization_id,
                )
                .order_by(AssetRow.created_at, AssetRow.asset_id)
            ).all()
            return tuple(self._asset(row) for row in rows)

    def create_pending_asset(self, asset: Asset) -> Asset:
        asset = validate_asset_object_key(Asset.model_validate(asset))
        if asset.status is not AssetStatus.PENDING:
            raise ValueError("A new asset must be pending")
        try:
            with self._session_factory.begin() as db:
                session = db.scalar(
                    select(DesignSessionRow)
                    .join(ProjectRow, ProjectRow.project_id == DesignSessionRow.project_id)
                    .where(
                        DesignSessionRow.session_id == asset.session_id,
                        DesignSessionRow.project_id == asset.project_id,
                        ProjectRow.organization_id == asset.organization_id,
                    )
                )
                if session is None:
                    raise OwnershipMismatchError(
                        "Asset session, project, and organization scope do not agree"
                    )
                if asset.parent_asset_id is not None:
                    parent = db.scalar(
                        select(AssetRow).where(
                            AssetRow.asset_id == asset.parent_asset_id,
                            AssetRow.organization_id == asset.organization_id,
                            AssetRow.project_id == asset.project_id,
                            AssetRow.session_id == asset.session_id,
                        )
                    )
                    if parent is None:
                        raise OwnershipMismatchError("Parent asset not found in asset scope")
                if asset.generation_run_id is not None:
                    run_row = db.scalar(
                        select(GenerationRunRow).where(
                            GenerationRunRow.generation_run_id == asset.generation_run_id,
                            GenerationRunRow.session_id == asset.session_id,
                        )
                    )
                    if run_row is None:
                        raise OwnershipMismatchError("Generation run not found in asset scope")
                    run = self._generation_run(run_row)
                    if run.status is not GenerationStatus.SUCCEEDED or run.result is None:
                        raise AssetLineageError(
                            "Generated assets require a succeeded generation run"
                        )
                    output = next(
                        (
                            item
                            for item in run.result.outputs
                            if item.ordinal == asset.generation_output_ordinal
                        ),
                        None,
                    )
                    if output is None:
                        raise AssetLineageError("Generation output ordinal does not exist")
                    if output.media_type != "image":
                        raise AssetLineageError("Generation output is not an image")
                    if output.provider_output_id != asset.provider_output_id:
                        raise AssetLineageError(
                            "Provider output ID does not match generation output"
                        )
                db.add(self._asset_row(asset))
        except IntegrityError as exc:
            raise AssetConflictError(
                "Asset identity, object key, or generation output already exists"
            ) from exc
        return asset

    def mark_asset_ready(self, asset_id: UUID, organization_id: UUID, ready_at: datetime) -> Asset:
        with self._session_factory.begin() as db:
            row = self._pending_asset_row(db, asset_id, organization_id)
            row.status = AssetStatus.READY.value
            row.ready_at = ready_at
            return self._asset(row)

    def mark_asset_failed(
        self,
        asset_id: UUID,
        organization_id: UUID,
        error_code: AssetErrorCode,
        error_detail: str,
        failed_at: datetime,
    ) -> Asset:
        error_code = AssetErrorCode(error_code)
        with self._session_factory.begin() as db:
            row = self._pending_asset_row(db, asset_id, organization_id)
            row.status = AssetStatus.FAILED.value
            row.failed_at = failed_at
            row.error_code = error_code.value
            row.error_detail = error_detail
            return self._asset(row)

    def claim_generation_run(
        self,
        session_id: UUID,
        generation_run_id: UUID,
        organization_id: UUID,
        started_at: datetime,
    ) -> GenerationRun:
        with self._session_factory.begin() as db:
            scoped_sessions = self._scoped_session_ids(organization_id)
            result = db.execute(
                update(GenerationRunRow)
                .where(
                    GenerationRunRow.generation_run_id == generation_run_id,
                    GenerationRunRow.session_id == session_id,
                    GenerationRunRow.session_id.in_(scoped_sessions),
                    GenerationRunRow.status == GenerationStatus.PENDING.value,
                )
                .values(status=GenerationStatus.RUNNING.value, started_at=started_at)
            )
            if result.rowcount != 1:
                existing = db.scalar(
                    select(GenerationRunRow.status).where(
                        GenerationRunRow.generation_run_id == generation_run_id,
                        GenerationRunRow.session_id == session_id,
                        GenerationRunRow.session_id.in_(scoped_sessions),
                    )
                )
                if existing is None:
                    raise OwnershipMismatchError("Generation run not found in organization scope")
                raise GenerationStateConflictError(
                    f"Generation run cannot be claimed from {existing} status"
                )
            row = db.get(GenerationRunRow, generation_run_id)
            return self._generation_run(row)

    def complete_generation_run(
        self,
        session_id: UUID,
        generation_run_id: UUID,
        organization_id: UUID,
        result: GenerationResult,
        completed_at: datetime,
    ) -> GenerationRun:
        result = GenerationResult.model_validate(result)
        with self._session_factory.begin() as db:
            row = self._running_generation_row(db, session_id, generation_run_id, organization_id)
            prompt = db.get(PromptRevisionRow, row.prompt_revision_id)
            compiled = self._compiled_prompt(prompt)
            request = GenerationRequest(
                generation_run_id=row.generation_run_id,
                prompt_revision_id=row.prompt_revision_id,
                compiled_prompt=compiled,
                provider=row.provider,
                model=row.model,
                configuration=row.configuration,
            )
            result = validate_generation_result(request, result)
            row.status = GenerationStatus.SUCCEEDED.value
            row.provider_request_id = result.provider_request_id
            row.result_payload = result.model_dump(mode="json")
            row.completed_at = completed_at
            return self._generation_run(row)

    def fail_generation_run(
        self,
        session_id: UUID,
        generation_run_id: UUID,
        organization_id: UUID,
        error_code: GenerationErrorCode,
        error_detail: str,
        completed_at: datetime,
    ) -> GenerationRun:
        error_code = GenerationErrorCode(error_code)
        with self._session_factory.begin() as db:
            row = self._running_generation_row(db, session_id, generation_run_id, organization_id)
            row.status = GenerationStatus.FAILED.value
            row.error_code = error_code.value
            row.error_detail = error_detail
            row.completed_at = completed_at
            return self._generation_run(row)

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
    def _generation_row(run: GenerationRun) -> GenerationRunRow:
        return GenerationRunRow(
            generation_run_id=run.generation_run_id,
            session_id=run.session_id,
            prompt_revision_id=run.prompt_revision_id,
            prompt_content_hash=run.prompt_content_hash,
            profile_id=run.profile_id,
            profile_version=run.profile_version,
            provider=run.provider,
            model=run.model,
            configuration=run.configuration.model_dump(mode="json"),
            status=run.status.value,
            attempt=run.attempt,
            parent_generation_run_id=run.parent_generation_run_id,
            provider_request_id=None,
            result_payload=None,
            error_code=None,
            error_detail=None,
            created_at=run.created_at,
            started_at=None,
            completed_at=None,
        )

    def _add_generation_run(
        self, db: Session, run: GenerationRun, organization_id: UUID
    ) -> DesignSessionRow:
        if run.status is not GenerationStatus.PENDING:
            raise ValueError("A new generation run must be pending")
        if run.attempt != 1 or run.parent_generation_run_id is not None:
            raise ValueError("Generation Run v1 creates only initial attempt-1 runs")
        session = db.scalar(self._scoped_session_query(run.session_id, organization_id))
        if session is None:
            raise OwnershipMismatchError("Session not found in organization scope")
        prompt = db.scalar(
            select(PromptRevisionRow).where(
                PromptRevisionRow.prompt_revision_id == run.prompt_revision_id,
                PromptRevisionRow.session_id == run.session_id,
            )
        )
        if prompt is None:
            raise OwnershipMismatchError(
                "Prompt revision does not belong to generation run session"
            )
        compiled = self._compiled_prompt(prompt)
        if compiled.content_hash != run.prompt_content_hash:
            raise ValueError("Generation run prompt hash does not match prompt revision")
        db.add(self._generation_row(run))
        return session

    @staticmethod
    def _generation_run(row: GenerationRunRow) -> GenerationRun:
        return GenerationRun(
            generation_run_id=row.generation_run_id,
            session_id=row.session_id,
            prompt_revision_id=row.prompt_revision_id,
            prompt_content_hash=row.prompt_content_hash,
            profile_id=row.profile_id,
            profile_version=row.profile_version,
            provider=row.provider,
            model=row.model,
            configuration=row.configuration,
            status=row.status,
            attempt=row.attempt,
            parent_generation_run_id=row.parent_generation_run_id,
            result=row.result_payload,
            error_code=row.error_code,
            error_detail=row.error_detail,
            created_at=PersistenceRepository._utc(row.created_at),
            started_at=(
                PersistenceRepository._utc(row.started_at) if row.started_at is not None else None
            ),
            completed_at=(
                PersistenceRepository._utc(row.completed_at)
                if row.completed_at is not None
                else None
            ),
        )

    @staticmethod
    def _asset_row(asset: Asset) -> AssetRow:
        return AssetRow(
            asset_id=asset.asset_id,
            organization_id=asset.organization_id,
            project_id=asset.project_id,
            session_id=asset.session_id,
            kind=asset.kind.value,
            status=asset.status.value,
            object_key=asset.object_key,
            content_type=asset.content_type.value,
            content_hash=asset.content_hash,
            byte_size=asset.byte_size,
            generation_run_id=asset.generation_run_id,
            generation_output_ordinal=asset.generation_output_ordinal,
            provider_output_id=asset.provider_output_id,
            parent_asset_id=asset.parent_asset_id,
            created_at=asset.created_at,
            ready_at=asset.ready_at,
            failed_at=asset.failed_at,
            error_code=asset.error_code.value if asset.error_code is not None else None,
            error_detail=asset.error_detail,
        )

    @staticmethod
    def _asset(row: AssetRow) -> Asset:
        return Asset(
            asset_id=row.asset_id,
            organization_id=row.organization_id,
            project_id=row.project_id,
            session_id=row.session_id,
            kind=row.kind,
            status=row.status,
            object_key=row.object_key,
            content_type=row.content_type,
            content_hash=row.content_hash,
            byte_size=row.byte_size,
            generation_run_id=row.generation_run_id,
            generation_output_ordinal=row.generation_output_ordinal,
            provider_output_id=row.provider_output_id,
            parent_asset_id=row.parent_asset_id,
            created_at=PersistenceRepository._utc(row.created_at),
            ready_at=(PersistenceRepository._utc(row.ready_at) if row.ready_at else None),
            failed_at=(PersistenceRepository._utc(row.failed_at) if row.failed_at else None),
            error_code=row.error_code,
            error_detail=row.error_detail,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def _running_generation_row(
        self,
        db: Session,
        session_id: UUID,
        generation_run_id: UUID,
        organization_id: UUID,
    ) -> GenerationRunRow:
        row = db.scalar(
            select(GenerationRunRow)
            .where(
                GenerationRunRow.generation_run_id == generation_run_id,
                GenerationRunRow.session_id == session_id,
                GenerationRunRow.session_id.in_(self._scoped_session_ids(organization_id)),
            )
            .with_for_update()
        )
        if row is None:
            raise OwnershipMismatchError("Generation run not found in organization scope")
        if row.status != GenerationStatus.RUNNING.value:
            raise GenerationStateConflictError(
                f"Generation run cannot complete from {row.status} status"
            )
        return row

    def _pending_asset_row(self, db: Session, asset_id: UUID, organization_id: UUID) -> AssetRow:
        row = db.scalar(
            select(AssetRow)
            .where(
                AssetRow.asset_id == asset_id,
                AssetRow.organization_id == organization_id,
                AssetRow.session_id.in_(self._scoped_session_ids(organization_id)),
            )
            .with_for_update()
        )
        if row is None:
            raise OwnershipMismatchError("Asset not found in organization scope")
        if row.status != AssetStatus.PENDING.value:
            raise AssetConflictError(f"Asset cannot transition from {row.status} status")
        return row

    @staticmethod
    def _scoped_session_ids(organization_id: UUID):
        return (
            select(DesignSessionRow.session_id)
            .join(ProjectRow, ProjectRow.project_id == DesignSessionRow.project_id)
            .where(ProjectRow.organization_id == organization_id)
        )

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
