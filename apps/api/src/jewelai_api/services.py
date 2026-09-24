"""Application orchestration over domain transitions and scoped persistence."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from jewelai_domain import (
    SCHEMA_VERSION,
    AskDecision,
    Design,
    DesignRevision,
    RevisionConflict,
    confirm_field,
    lock_field,
    revise_design,
    unlock_field,
)
from jewelai_domain.models import MessageSource, RevisionEvent
from jewelai_persistence.models import DesignSessionRow, QuestionEventRow
from jewelai_persistence.repository import PersistenceRepository, StaleRevisionError

from .artifacts import ArtifactConfigurationError, RuntimeArtifacts
from .schemas import (
    ArtifactPins,
    ConfirmRevisionRequest,
    CreateSessionRequest,
    EditRevisionRequest,
    EvaluateRequest,
    EvaluationResponse,
    LockRevisionRequest,
    SessionResponse,
    UnlockRevisionRequest,
)


class ApplicationError(RuntimeError):
    pass


class InvalidTransitionError(ApplicationError):
    pass


class LockedFieldConflictError(ApplicationError):
    pass


class RuntimeService:
    def __init__(
        self,
        repository: PersistenceRepository,
        artifacts: RuntimeArtifacts,
        *,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], UUID] | None = None,
    ):
        self.repository = repository
        self.artifacts = artifacts
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uuid = uuid_factory or uuid4

    def create_organization(self, name: str):
        return self.repository.create_organization(self._uuid(), name, self._clock())

    def create_project(self, organization_id: UUID, name: str):
        return self.repository.create_project(self._uuid(), organization_id, name, self._clock())

    def create_session(
        self,
        project_id: UUID,
        organization_id: UUID,
        request: CreateSessionRequest,
    ) -> SessionResponse:
        profile = self.artifacts.roles.get_profile(request.role_id)
        locale = self.artifacts.roles.resolve_locale(profile.role_id, request.locale)
        now = self._clock()
        session_id = self._uuid()
        revision = DesignRevision(
            schema_version=SCHEMA_VERSION,
            design_id=self._uuid(),
            revision_id=self._uuid(),
            revision=1,
            parent_revision_id=None,
            created_at=now,
            event=RevisionEvent(
                action="create",
                source=MessageSource(
                    message_id=f"session:{session_id}:create",
                    recorded_at=now,
                ),
                reason="Session created with an empty design intake",
            ),
            design=Design(),
        )
        versions = self.artifacts.versions
        row = DesignSessionRow(
            session_id=session_id,
            project_id=project_id,
            role_id=profile.role_id.value,
            locale=locale,
            created_at=now,
            updated_at=now,
            current_revision_id=revision.revision_id,
            design_schema_version=SCHEMA_VERSION,
            role_artifact_version=versions.roles,
            dictionary_artifact_version=versions.dictionary,
            question_artifact_version=versions.questions,
            rules_artifact_version=versions.rules,
        )
        self.repository.create_design_session(row, revision, organization_id=organization_id)
        return self._session_response(row)

    def get_session(self, session_id: UUID, organization_id: UUID) -> SessionResponse:
        row = self.repository.get_design_session(session_id, organization_id)
        return self._session_response(row)

    def transition_revision(self, session_id: UUID, organization_id: UUID, request):
        current = self.repository.get_current_revision(session_id, organization_id)
        now = self._clock()
        common = {
            "expected_revision_id": request.expected_revision_id,
            "source": request.source,
            "reason": request.reason,
            "created_at": now,
        }
        try:
            if isinstance(request, EditRevisionRequest):
                revision = revise_design(current, request.proposed_design, **common)
            elif isinstance(request, ConfirmRevisionRequest):
                revision = confirm_field(current, request.target, **common)
            elif isinstance(request, LockRevisionRequest):
                revision = lock_field(current, request.target, **common)
            elif isinstance(request, UnlockRevisionRequest):
                revision = unlock_field(current, request.target, **common)
            else:
                raise InvalidTransitionError("Unsupported revision transition")
        except RevisionConflict as exc:
            if "Stale revision" in str(exc):
                raise StaleRevisionError(str(exc)) from exc
            if "Locked field" in str(exc):
                raise LockedFieldConflictError(str(exc)) from exc
            raise InvalidTransitionError(str(exc)) from exc
        return self.repository.append_revision_cas(
            session_id,
            organization_id,
            request.expected_revision_id,
            revision,
        )

    def evaluate(
        self,
        session_id: UUID,
        organization_id: UUID,
        request: EvaluateRequest,
    ) -> EvaluationResponse:
        session = self.repository.get_design_session(session_id, organization_id)
        self._assert_artifact_pins(session)
        revision = self.repository.get_revision(
            session_id, session.current_revision_id, organization_id
        )
        decision = self.artifacts.rules.evaluate(
            revision,
            session.role_id,
            knowledge_facts=request.knowledge_facts,
            proposed_update=request.proposed_update,
        )
        rendered = None
        if isinstance(decision, AskDecision):
            rendered = self.artifacts.questions.render(
                decision.question_id, session.role_id, session.locale
            )
            self.repository.add_question_event(
                QuestionEventRow(
                    event_id=self._uuid(),
                    session_id=session_id,
                    specification_revision_id=revision.revision_id,
                    semantic_question_id=decision.question_id.value,
                    rules_artifact_version=decision.rules_artifact_version,
                    rule_id=decision.rule_id,
                    rule_version=decision.rule_version,
                    target=decision.target.value,
                    concrete_target=decision.concrete_target,
                    decision=decision.decision,
                    reason_code=decision.reason_code.value,
                    trace_payload=decision.model_dump(mode="json"),
                    created_at=self._clock(),
                ),
                organization_id,
            )
        return EvaluationResponse(
            revision_id=revision.revision_id,
            decision=decision,
            rendered_question=rendered,
        )

    def _assert_artifact_pins(self, row: DesignSessionRow) -> None:
        versions = self.artifacts.versions
        stored = (
            row.design_schema_version,
            row.role_artifact_version,
            row.dictionary_artifact_version,
            row.question_artifact_version,
            row.rules_artifact_version,
        )
        loaded = (
            SCHEMA_VERSION,
            versions.roles,
            versions.dictionary,
            versions.questions,
            versions.rules,
        )
        if stored != loaded:
            raise ArtifactConfigurationError(
                "Session artifact pins are unavailable in the configured runtime"
            )

    @staticmethod
    def _session_response(row: DesignSessionRow) -> SessionResponse:
        def utc(value: datetime) -> datetime:
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        return SessionResponse(
            session_id=row.session_id,
            project_id=row.project_id,
            role_id=row.role_id,
            locale=row.locale,
            created_at=utc(row.created_at),
            updated_at=utc(row.updated_at),
            current_revision_id=row.current_revision_id,
            artifacts=ArtifactPins(
                design_schema=row.design_schema_version,
                roles=row.role_artifact_version,
                dictionary=row.dictionary_artifact_version,
                questions=row.question_artifact_version,
                rules=row.rules_artifact_version,
            ),
        )
