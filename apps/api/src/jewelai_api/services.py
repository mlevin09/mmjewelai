"""Application orchestration over domain transitions and scoped persistence."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from jewelai_assets import (
    AssetAccessPolicy,
    PrivateObjectAccessSigner,
    SignedAssetReadAccess,
    issue_asset_read_access,
)
from jewelai_auth import (
    AuthenticatedPrincipal,
    MembershipRole,
    VerifiedIdentity,
    require_can_add_membership,
    require_can_change_membership,
    require_can_list_memberships,
    require_can_remove_membership,
)
from jewelai_domain import (
    SCHEMA_VERSION,
    AskDecision,
    Design,
    DesignRevision,
    ReadyDecision,
    RevisionConflict,
    confirm_field,
    lock_field,
    revise_design,
    unlock_field,
)
from jewelai_domain.models import MessageSource, RevisionEvent
from jewelai_model_gateway import GenerationRun, GenerationStatus
from jewelai_parser import ParserProposal, build_parser_proposal
from jewelai_persistence.models import (
    DesignSessionRow,
    MessageRow,
    PromptRevisionRow,
    QuestionEventRow,
)
from jewelai_persistence.repository import PersistenceRepository, StaleRevisionError
from jewelai_prompts import compile_prompt, validate_compiled_prompt

from .artifacts import ArtifactConfigurationError, RuntimeArtifacts
from .generation import GenerationProfileRegistry
from .schemas import (
    ArtifactPins,
    AssetListResponse,
    AssetResponse,
    ConfirmRevisionRequest,
    CreateGenerationRunRequest,
    CreatePromptRevisionRequest,
    CreateSessionRequest,
    EditRevisionRequest,
    EvaluateRequest,
    EvaluationResponse,
    GenerationRunListResponse,
    LockRevisionRequest,
    MembershipListResponse,
    MembershipResponse,
    MeResponse,
    MessageResponse,
    ParserProposalRequest,
    PrincipalMembership,
    PromptRevisionListResponse,
    PromptRevisionResponse,
    SessionResponse,
    UnlockRevisionRequest,
)


class ApplicationError(RuntimeError):
    pass


class InvalidTransitionError(ApplicationError):
    pass


class LockedFieldConflictError(ApplicationError):
    pass


class SpecificationNotReadyError(ApplicationError):
    def __init__(self, decision):
        super().__init__("Specification is not ready for prompt compilation")
        self.decision = decision


class RuntimeService:
    def __init__(
        self,
        repository: PersistenceRepository,
        artifacts: RuntimeArtifacts,
        *,
        asset_access_signer: PrivateObjectAccessSigner,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], UUID] | None = None,
        before_prompt_persist: Callable[[], None] | None = None,
        generation_profiles: GenerationProfileRegistry | None = None,
        asset_access_policy: AssetAccessPolicy | None = None,
    ):
        self.repository = repository
        self.artifacts = artifacts
        self._clock = clock or (lambda: datetime.now(UTC))
        self._uuid = uuid_factory or uuid4
        self._before_prompt_persist = before_prompt_persist
        self._generation_profiles = generation_profiles or GenerationProfileRegistry()
        self._asset_access_signer = asset_access_signer
        self._asset_access_policy = asset_access_policy or AssetAccessPolicy()

    def resolve_identity(self, identity: VerifiedIdentity) -> AuthenticatedPrincipal:
        row = self.repository.get_or_create_principal(identity, self._uuid(), self._clock())
        return AuthenticatedPrincipal(
            principal_id=row.principal_id,
            email=row.email,
            display_name=row.display_name,
        )

    def create_organization(self, name: str, principal_id: UUID | None = None):
        if principal_id is None:
            return self.repository.create_organization(self._uuid(), name, self._clock())
        return self.repository.create_organization_with_owner(
            self._uuid(), name, principal_id, self._clock()
        )

    def require_organization_member(
        self, organization_id: UUID, principal_id: UUID
    ) -> MembershipRole:
        return MembershipRole(self.repository.get_membership(organization_id, principal_id).role)

    def get_me(self, principal: AuthenticatedPrincipal) -> MeResponse:
        memberships = self.repository.list_principal_memberships(principal.principal_id)
        return MeResponse(
            principal_id=principal.principal_id,
            email=principal.email,
            display_name=principal.display_name,
            memberships=tuple(
                PrincipalMembership(
                    organization_id=membership.organization_id,
                    organization_name=organization.name,
                    role=MembershipRole(membership.role),
                )
                for membership, organization in memberships
            ),
        )

    def list_memberships(self, organization_id: UUID, actor_id: UUID) -> MembershipListResponse:
        actor = self.require_organization_member(organization_id, actor_id)
        require_can_list_memberships(actor)
        return MembershipListResponse(
            memberships=tuple(
                self._membership_response(membership, principal)
                for membership, principal in self.repository.list_organization_memberships(
                    organization_id
                )
            )
        )

    def add_membership(
        self,
        organization_id: UUID,
        actor_id: UUID,
        principal_id: UUID,
        role: MembershipRole,
    ) -> MembershipResponse:
        actor = self.require_organization_member(organization_id, actor_id)
        require_can_add_membership(actor, role)
        row = self.repository.add_membership(organization_id, principal_id, role, self._clock())
        return self._membership_response(row, self.repository.get_principal(principal_id))

    def update_membership(
        self,
        organization_id: UUID,
        actor_id: UUID,
        principal_id: UUID,
        role: MembershipRole,
    ) -> MembershipResponse:
        actor = self.require_organization_member(organization_id, actor_id)
        current = self.repository.get_membership(organization_id, principal_id)
        require_can_change_membership(actor, MembershipRole(current.role), role)
        row = self.repository.update_membership_role(
            organization_id, principal_id, role, self._clock()
        )
        return self._membership_response(row, self.repository.get_principal(principal_id))

    def delete_membership(self, organization_id: UUID, actor_id: UUID, principal_id: UUID) -> None:
        actor = self.require_organization_member(organization_id, actor_id)
        target = self.repository.get_membership(organization_id, principal_id)
        require_can_remove_membership(actor, MembershipRole(target.role))
        self.repository.delete_membership(organization_id, principal_id)

    def create_project(self, organization_id: UUID, name: str):
        return self.repository.create_project(self._uuid(), organization_id, name, self._clock())

    @staticmethod
    def _membership_response(membership, principal) -> MembershipResponse:
        return MembershipResponse(
            principal_id=principal.principal_id,
            email=principal.email,
            display_name=principal.display_name,
            role=MembershipRole(membership.role),
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )

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
            prompt_artifact_version=versions.prompts,
        )
        self.repository.create_design_session(row, revision, organization_id=organization_id)
        return self._session_response(row)

    def get_session(self, session_id: UUID, organization_id: UUID) -> SessionResponse:
        row = self.repository.get_design_session(session_id, organization_id)
        return self._session_response(row)

    def create_message(
        self, session_id: UUID, organization_id: UUID, content: str
    ) -> MessageResponse:
        now = self._clock()
        row = MessageRow(
            message_id=self._uuid(),
            session_id=session_id,
            actor="user",
            content=content,
            created_at=now,
        )
        self.repository.create_message(row, organization_id)
        return self._message_response(row)

    def create_parser_proposal(
        self,
        session_id: UUID,
        organization_id: UUID,
        request: ParserProposalRequest,
    ) -> ParserProposal:
        session = self.repository.get_design_session(session_id, organization_id)
        self._assert_artifact_pins(session)
        if session.current_revision_id != request.expected_revision_id:
            raise StaleRevisionError("Current revision changed before parser proposal creation")
        message = self.repository.get_message(session_id, request.message_id, organization_id)
        revision = self.repository.get_revision(
            session_id, request.expected_revision_id, organization_id
        )
        proposal = build_parser_proposal(
            revision,
            expected_revision_id=request.expected_revision_id,
            source=MessageSource(
                message_id=str(message.message_id),
                recorded_at=self._utc(message.created_at),
            ),
            locale=session.locale,
            dictionary=self.artifacts.dictionary,
            candidate=request.candidate,
        )
        latest = self.repository.get_design_session(session_id, organization_id)
        if latest.current_revision_id != request.expected_revision_id:
            raise StaleRevisionError("Current revision changed during parser proposal creation")
        return proposal

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

    def create_prompt_revision(
        self,
        session_id: UUID,
        organization_id: UUID,
        request: CreatePromptRevisionRequest,
    ) -> PromptRevisionResponse:
        session = self.repository.get_design_session(session_id, organization_id)
        self._assert_artifact_pins(session)
        if session.current_revision_id != request.expected_revision_id:
            raise StaleRevisionError("Current revision changed before prompt compilation")
        revision = self.repository.get_revision(
            session_id, request.expected_revision_id, organization_id
        )
        decision = self.artifacts.rules.evaluate(revision, session.role_id)
        if not isinstance(decision, ReadyDecision):
            raise SpecificationNotReadyError(decision)
        compiled = compile_prompt(revision, self.artifacts.prompts)
        validate_compiled_prompt(compiled, revision, self.artifacts.prompts)
        if self._before_prompt_persist is not None:
            self._before_prompt_persist()
        row = PromptRevisionRow(
            prompt_revision_id=self._uuid(),
            session_id=session_id,
            specification_revision_id=revision.revision_id,
            prompt_schema_version=compiled.schema_version,
            compiler_version=compiled.compiler_version,
            template_id=compiled.template_id,
            template_version=compiled.template_version,
            template_artifact_version=compiled.template_artifact_version,
            compiled_text=compiled.prompt_text,
            structured_payload=compiled.model_dump(mode="json"),
            content_hash=compiled.content_hash,
            created_at=self._clock(),
        )
        self.repository.create_prompt_revision(
            row, compiled, organization_id, request.expected_revision_id
        )
        return self._prompt_response(row, compiled)

    def get_prompt_revision(
        self, session_id: UUID, prompt_revision_id: UUID, organization_id: UUID
    ) -> PromptRevisionResponse:
        row, compiled = self.repository.get_prompt_revision(
            session_id, prompt_revision_id, organization_id
        )
        return self._prompt_response(row, compiled)

    def list_prompt_revisions(
        self, session_id: UUID, organization_id: UUID
    ) -> PromptRevisionListResponse:
        return PromptRevisionListResponse(
            prompt_revisions=tuple(
                self._prompt_response(row, compiled)
                for row, compiled in self.repository.list_prompt_revisions(
                    session_id, organization_id
                )
            )
        )

    def create_generation_run(
        self,
        session_id: UUID,
        organization_id: UUID,
        request: CreateGenerationRunRequest,
    ) -> GenerationRun:
        prompt_row, compiled = self.repository.get_prompt_revision(
            session_id, request.prompt_revision_id, organization_id
        )
        profile = self._generation_profiles.get(request.profile_id)
        now = self._clock()
        run = GenerationRun(
            generation_run_id=self._uuid(),
            session_id=session_id,
            prompt_revision_id=prompt_row.prompt_revision_id,
            prompt_content_hash=compiled.content_hash,
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            provider=profile.provider,
            model=profile.model,
            configuration=profile.configuration,
            status=GenerationStatus.PENDING,
            attempt=1,
            created_at=now,
        )
        return self.repository.create_generation_run(run, organization_id)

    def get_generation_run(
        self, session_id: UUID, generation_run_id: UUID, organization_id: UUID
    ) -> GenerationRun:
        return self.repository.get_generation_run(session_id, generation_run_id, organization_id)

    def list_generation_runs(
        self, session_id: UUID, organization_id: UUID
    ) -> GenerationRunListResponse:
        return GenerationRunListResponse(
            generation_runs=self.repository.list_generation_runs(session_id, organization_id)
        )

    def get_asset(self, session_id: UUID, asset_id: UUID, organization_id: UUID) -> AssetResponse:
        return self._asset_response(
            self.repository.get_asset(session_id, asset_id, organization_id)
        )

    def list_assets(self, session_id: UUID, organization_id: UUID) -> AssetListResponse:
        return AssetListResponse(
            assets=tuple(
                self._asset_response(asset)
                for asset in self.repository.list_assets(session_id, organization_id)
            )
        )

    def create_asset_read_access(
        self,
        session_id: UUID,
        asset_id: UUID,
        organization_id: UUID,
        requested_ttl_seconds: int | None,
    ) -> SignedAssetReadAccess:
        asset = self.repository.get_asset(session_id, asset_id, organization_id)
        return issue_asset_read_access(
            asset,
            self._asset_access_signer,
            requested_ttl_seconds=requested_ttl_seconds,
            policy=self._asset_access_policy,
            clock=self._clock,
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
            row.prompt_artifact_version,
        )
        loaded = (
            SCHEMA_VERSION,
            versions.roles,
            versions.dictionary,
            versions.questions,
            versions.rules,
            versions.prompts,
        )
        if stored != loaded:
            raise ArtifactConfigurationError(
                "Session artifact pins are unavailable in the configured runtime"
            )

    @staticmethod
    def _session_response(row: DesignSessionRow) -> SessionResponse:
        return SessionResponse(
            session_id=row.session_id,
            project_id=row.project_id,
            role_id=row.role_id,
            locale=row.locale,
            created_at=RuntimeService._utc(row.created_at),
            updated_at=RuntimeService._utc(row.updated_at),
            current_revision_id=row.current_revision_id,
            artifacts=ArtifactPins(
                design_schema=row.design_schema_version,
                roles=row.role_artifact_version,
                dictionary=row.dictionary_artifact_version,
                questions=row.question_artifact_version,
                rules=row.rules_artifact_version,
                prompts=row.prompt_artifact_version,
            ),
        )

    @staticmethod
    def _prompt_response(row: PromptRevisionRow, compiled) -> PromptRevisionResponse:
        return PromptRevisionResponse(
            prompt_revision_id=row.prompt_revision_id,
            session_id=row.session_id,
            specification_revision_id=row.specification_revision_id,
            compiled_prompt=compiled,
            created_at=RuntimeService._utc(row.created_at),
        )

    @staticmethod
    def _asset_response(asset) -> AssetResponse:
        return AssetResponse(
            schema_version=asset.schema_version,
            asset_id=asset.asset_id,
            session_id=asset.session_id,
            kind=asset.kind,
            status=asset.status,
            content_type=asset.content_type,
            content_hash=asset.content_hash,
            byte_size=asset.byte_size,
            generation_run_id=asset.generation_run_id,
            generation_output_ordinal=asset.generation_output_ordinal,
            parent_asset_id=asset.parent_asset_id,
            created_at=asset.created_at,
            ready_at=asset.ready_at,
            failed_at=asset.failed_at,
            error_code=asset.error_code,
            error_detail=asset.error_detail,
        )

    @staticmethod
    def _message_response(row: MessageRow) -> MessageResponse:
        return MessageResponse(
            message_id=row.message_id,
            session_id=row.session_id,
            actor="user",
            content=row.content,
            created_at=RuntimeService._utc(row.created_at),
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
