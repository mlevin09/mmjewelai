"""Internal Prompt Enrichment runtime orchestration.

This module is deliberately not wired to FastAPI.  It coordinates the existing deterministic
parser, enrichment, clarification/correction, durable persistence, and Step #12 output boundaries
without changing any public route or invoking an external provider.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from jewelai_domain.knowledge_activation import (
    ActiveKnowledgeRuntime,
    ProductionValidationReport,
)
from jewelai_domain.knowledge_runtime import bind_verified_release, knowledge_store_version
from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)
from jewelai_domain.models import ImmutableModel, MessageSource
from jewelai_domain.revisions import RevisionConflict, revise_design
from jewelai_parser import AnyParserProposal, FullMessageParseResult, parse_full_message
from jewelai_persistence import (
    ClarificationDecisionConflictError,
    ClarificationDecisionIntegrityError,
    ClarificationPlanIntegrityError,
    EnrichmentCycleConflictError,
    EnrichmentIntegrityError,
    KnowledgeReleasePinConflictError,
    NotFoundError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleRevisionError,
    UserCorrectionConflictError,
    UserCorrectionIntegrityError,
)
from jewelai_prompts import (
    CanonicalFinalPromptAssemblyV2_1 as FinalPromptAssembly,
)
from jewelai_prompts import (
    CanonicalInternalFinalPromptHandoffV2_1 as InternalFinalPromptHandoff,
)
from jewelai_prompts import (
    FinalPromptArtifactVersions,
    FinalPromptDecisionLineage,
    FinalPromptInputError,
    FinalPromptReadiness,
    FinalPromptSnapshot,
    InternalFinalPromptHandoffError,
    KnowledgeReleaseReference,
    assemble_internal_final_prompt,
    build_internal_final_prompt_handoff,
    enrich_prompt_with_active_release,
)
from jewelai_prompts.downstream_preparation import (
    DecisionFrontier,
    DecisionReference,
    GenerationPreparationError,
    PreparationGateEvidence,
    preparation_hash,
    render_semantic_source,
)

from .artifacts import RuntimeArtifacts
from .clarification import (
    ClarificationImportance,
    ClarificationPlan,
    UnaskedReason,
    continue_clarification_plan,
    plan_clarifications,
)
from .clarification_answers import (
    ClarificationAnswer,
    ClarificationAnswerError,
    ClarificationAnswerErrorCode,
    ClarificationAnswerResult,
    ClarificationDecision,
    process_clarification_answer,
)
from .constraint_evidence import merge_constraint_evidence
from .correction_enrichment import (
    CorrectionErrorCode,
    CorrectionInputError,
    CorrectionOutcome,
    CorrectionReason,
    CorrectionReenrichmentResult,
    UserCorrection,
    process_user_correction,
)
from .durable_enrichment import (
    commit_clarification_answer_result,
    commit_user_correction_result,
    list_clarification_answer_results,
    list_user_correction_results,
)
from .parametric_enrichment import select_parametric_references
from .parsed_enrichment import (
    CandidateDispositionOutcome,
    CandidateDispositionReason,
    ParsedCandidateEnrichmentResult,
    enrich_parsed_candidates_with_active_release,
)
from .preparation_contracts import GenerationPreparationRequest


class PromptEnrichmentRuntimeErrorCode(StrEnum):
    SESSION_NOT_FOUND = "session_not_found"
    STALE_REVISION = "stale_revision"
    INVALID_KNOWLEDGE_RELEASE = "invalid_knowledge_release"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    ENRICHMENT_CYCLE_MISMATCH = "enrichment_cycle_mismatch"
    INVALID_HISTORY = "invalid_history"
    CONCURRENT_CONFLICT = "concurrent_conflict"
    FINAL_OUTPUT_BLOCKED = "final_output_blocked"
    INVALID_CLARIFICATION_ANSWER = "invalid_clarification_answer"
    INVALID_CLARIFICATION_DECISION = "invalid_clarification_decision"
    INVALID_CLARIFICATION_OPTION = "invalid_clarification_option"
    CLARIFICATION_CONFLICT = "clarification_conflict"
    INVALID_CLARIFICATION_PLAN = "invalid_clarification_plan"
    STALE_CLARIFICATION_PLAN = "stale_clarification_plan"
    INVALID_CORRECTION = "invalid_correction"
    CORRECTION_CONFLICT = "correction_conflict"


class PromptEnrichmentRuntimeError(RuntimeError):
    """Bounded internal workflow failure with no infrastructure detail leakage."""

    def __init__(self, code: PromptEnrichmentRuntimeErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class PromptEnrichmentWorkflowStatus(StrEnum):
    ENRICHMENT_COMPLETED = "enrichment_completed"
    CLARIFICATION_AVAILABLE = "clarification_available"
    BLOCKING_CLARIFICATION_UNRESOLVED = "blocking_clarification_unresolved"
    CLARIFICATION_ANSWER_RECORDED = "clarification_answer_recorded"
    CORRECTION_APPLIED = "correction_applied"
    CORRECTION_DEFERRED = "correction_deferred"
    FINAL_OUTPUT_READY = "final_output_ready"
    FINAL_OUTPUT_READY_WITH_UNRESOLVED = "final_output_ready_with_unresolved"
    FINAL_OUTPUT_BLOCKED = "final_output_blocked"


class InitialEnrichmentRequest(ImmutableModel):
    session_id: UUID
    organization_id: UUID
    expected_revision_id: UUID
    message_id: UUID


class PersistedClarificationAnswerRequest(ImmutableModel):
    session_id: UUID
    clarification_plan_id: UUID
    clarification_id: str
    decision: ClarificationDecision
    selected_option: str | None = None
    expected_revision_id: UUID
    answer_id: UUID
    message_id: UUID


class PersistedUserCorrectionRequest(ImmutableModel):
    session_id: UUID
    expected_revision_id: UUID
    message_id: UUID


class PromptEnrichmentWorkflowState(ImmutableModel):
    session_id: UUID
    organization_id: UUID
    authoritative_revision_id: UUID
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int
    knowledge_release: KnowledgeReleaseReference
    status: PromptEnrichmentWorkflowStatus
    clarification_plan_id: UUID | None = None
    clarification_plan: ClarificationPlan | None = None
    final_output: FinalPromptAssembly | None = None
    preparation_expectations: GenerationPreparationRequest | None = None
    can_prepare: bool = False


class InitialEnrichmentRuntimeResult(ImmutableModel):
    parse_result: FullMessageParseResult
    parser_proposal: AnyParserProposal
    enrichment: ParsedCandidateEnrichmentResult
    workflow: PromptEnrichmentWorkflowState


class PromptEnrichmentRuntimeService:
    """Session-aware internal facade over the existing approved module primitives."""

    def __init__(
        self,
        repository: PersistenceRepository,
        artifacts: RuntimeArtifacts,
        artifact_store: KnowledgeArtifactStore,
        *,
        knowledge_package_id: str,
        knowledge_artifact_version: str,
        active_release: ActiveKnowledgeRuntime | object,
        validation_report: ProductionValidationReport | object,
        clock: Callable[[], datetime],
        uuid_factory: Callable[[], UUID],
    ):
        self.repository = repository
        self.artifacts = artifacts
        self.artifact_store = artifact_store
        self.knowledge_package_id = knowledge_package_id
        self.knowledge_artifact_version = knowledge_artifact_version
        self.active_release = active_release
        self.validation_report = validation_report
        self._clock = clock
        self._uuid = uuid_factory

    def start_initial_message(
        self, request: InitialEnrichmentRequest
    ) -> InitialEnrichmentRuntimeResult:
        """Parse a persisted message first, then atomically commit revision + first cycle."""

        request = InitialEnrichmentRequest.model_validate(request)
        try:
            session = self.repository.get_design_session(
                request.session_id, request.organization_id
            )
            self._validate_session_artifacts(session)
            if session.current_revision_id != request.expected_revision_id:
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.STALE_REVISION,
                    "Product State revision changed before internal enrichment",
                )
            revision = self.repository.get_revision(
                request.session_id,
                request.expected_revision_id,
                request.organization_id,
            )
            message = self.repository.get_message(
                request.session_id, request.message_id, request.organization_id
            )
            verified = self._load_release()
            if knowledge_store_version(self.artifact_store) != "1.1.0":
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                    "New controlled enrichment sessions require Knowledge Contract 1.1.0",
                )
            release_binding = bind_verified_release(
                self.artifact_store,
                self.knowledge_package_id,
                self.knowledge_artifact_version,
                active_release=self.active_release,
                validation_report=self.validation_report,
            )
            source = MessageSource(
                message_id=str(message.message_id),
                recorded_at=_aware(message.created_at),
            )
            parsed = parse_full_message(
                message.content,
                locale=session.locale,
                dictionary=self.artifacts.dictionary,
                knowledge_runtime=verified.compiled_runtime,
            )
            first = self._evaluate(revision, parsed, source)
            resulting_revision = None
            authoritative = revision
            if first.parser_proposal.has_changes:
                authoritative = revise_design(
                    revision,
                    first.parser_proposal.proposed_design,
                    expected_revision_id=revision.revision_id,
                    source=source,
                    reason="Applied explicitly sourced internal full-message parsing",
                    created_at=self._clock(),
                )
                resulting_revision = authoritative
            enrichment = (
                self._evaluate(authoritative, parsed, source)
                if resulting_revision is not None
                else first
            )
            cycle_id = self._uuid()
            clarification_plan_id = self._uuid()
            constraint_evidence = merge_constraint_evidence(
                enrichment,
                session_id=request.session_id,
                organization_id=request.organization_id,
                source=source,
                authoritative_revision=authoritative,
                enrichment_cycle_id=cycle_id,
            )
            clarification = plan_clarifications(
                authoritative,
                enrichment,
                role_id=session.role_id,
                dictionary=self.artifacts.dictionary,
                questions=self.artifacts.questions,
                rules=self.artifacts.rules,
                constraint_evidence=constraint_evidence,
            )
            cycle = self.repository.commit_initial_enrichment(
                enrichment_cycle_id=cycle_id,
                session_id=request.session_id,
                organization_id=request.organization_id,
                expected_revision_id=request.expected_revision_id,
                resulting_revision=resulting_revision,
                result=enrichment.enrichment_result,
                created_at=self._clock(),
                clarification_plan_id=clarification_plan_id,
                clarification_plan_payload=clarification.model_dump(mode="json"),
                release_binding=release_binding,
            )
            workflow = self._state_from_cycle(
                session_id=request.session_id,
                organization_id=request.organization_id,
                cycle=cycle,
                clarification_plan_id=clarification_plan_id,
                clarification_plan=clarification,
            )
            return InitialEnrichmentRuntimeResult(
                parse_result=parsed,
                parser_proposal=first.parser_proposal,
                enrichment=enrichment,
                workflow=workflow,
            )
        except PromptEnrichmentRuntimeError:
            raise
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Session or message was not found in organization scope",
            ) from exc
        except StaleRevisionError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.STALE_REVISION,
                "Product State revision changed during internal enrichment",
            ) from exc
        except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                "The explicitly selected ACTIVE Knowledge release is unavailable or invalid",
            ) from exc
        except (EnrichmentCycleConflictError, RevisionConflict) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                "Concurrent Product State or enrichment-cycle update detected",
            ) from exc
        except ClarificationPlanIntegrityError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                "Clarification plan failed durable validation",
            ) from exc

    def build_preparation_source(self, repository, session_id, organization_id):
        """Restore the sole current source using the caller's already locked transaction reader."""
        snapshot = build_final_prompt_snapshot(
            repository,
            session_id=session_id,
            organization_id=organization_id,
            artifacts=self.artifacts,
            artifact_store=self.artifact_store,
            active_release=self.active_release,
            validation_report=self.validation_report,
        )
        record = repository.get_clarification_plan_for_cycle(
            session_id, snapshot.enrichment_cycle_id, organization_id
        )
        plan = ClarificationPlan.model_validate(record.plan_payload)
        assembly = assemble_internal_final_prompt(
            snapshot, dictionary=self.artifacts.dictionary, templates=self.artifacts.prompts
        )
        return self._preparation_context(repository, snapshot, assembly, record, plan)

    def _preparation_context(self, repository, snapshot, assembly, record, plan):
        session_id, organization_id = snapshot.session_id, snapshot.organization_id
        handoff = build_internal_final_prompt_handoff(assembly)
        frontier = DecisionFrontier(
            answers=tuple(
                sorted(
                    (
                        DecisionReference(
                            record_id=r.answer_record_id,
                            content_hash=r.result_payload["content_hash"],
                        )
                        for r in repository.list_clarification_answers(session_id, organization_id)
                    ),
                    key=lambda r: str(r.record_id),
                )
            ),
            corrections=tuple(
                sorted(
                    (
                        DecisionReference(
                            record_id=r.correction_record_id,
                            content_hash=r.result_payload["content_hash"],
                        )
                        for r in repository.list_user_corrections(session_id, organization_id)
                    ),
                    key=lambda r: str(r.record_id),
                )
            ),
        )
        gate = PreparationGateEvidence(
            organization_id=organization_id,
            session_id=session_id,
            revision=snapshot.revision,
            enrichment_cycle_id=snapshot.enrichment_cycle_id,
            enrichment_cycle_number=snapshot.enrichment_cycle_number,
            enrichment_result_hash=snapshot.enrichment_result.content_hash,
            source_handoff_hash=handoff.content_hash,
            knowledge_release=snapshot.knowledge_release,
            rule_decision=snapshot.rule_decision,
            workflow_status=_workflow_status(assembly, plan).value,
            clarification_plan_id=record.clarification_plan_id,
            clarification_plan_hash=record.content_hash,
            blocking_clarification_ids=tuple(
                sorted(
                    q.clarification_id
                    for q in plan.questions
                    if q.importance == ClarificationImportance.BLOCKING
                )
            ),
            decision_frontier=frontier,
            decision_frontier_hash=preparation_hash("jewelai.preparation.frontier/1.0.0", frontier),
            release_verified=True,
        )
        # The snapshot builder reloads and verifies actual runtime/report bytes against the pin.
        return handoff, gate

    def get_current_state(
        self, session_id: UUID, organization_id: UUID
    ) -> PromptEnrichmentWorkflowState:
        """Restore and verify the latest durable module state without changing it."""

        try:
            cycles = self.repository.list_enrichment_cycles(session_id, organization_id)
            if not cycles:
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH,
                    "Session has no durable enrichment cycle",
                )
            plan_id, plan = self._restore_plan_for_cycle(
                session_id, organization_id, cycles[-1].enrichment_cycle_id
            )
            return self._state_from_cycle(
                session_id=session_id,
                organization_id=organization_id,
                cycle=cycles[-1],
                clarification_plan_id=plan_id,
                clarification_plan=plan,
            )
        except PromptEnrichmentRuntimeError:
            raise
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Session was not found in organization scope",
            ) from exc
        except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                "Pinned ACTIVE Knowledge release failed integrity verification",
            ) from exc
        except (EnrichmentIntegrityError, ClarificationPlanIntegrityError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Durable enrichment or clarification history failed integrity verification",
            ) from exc

    def build_current_internal_final_prompt_handoff(
        self, session_id: UUID, organization_id: UUID
    ) -> InternalFinalPromptHandoff:
        """Build a read-only downstream handoff from current organization-scoped durable state."""

        state = self.get_current_state(session_id, organization_id)
        if state.final_output is None:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Authoritative final output is unavailable",
            )
        try:
            return build_internal_final_prompt_handoff(state.final_output)
        except InternalFinalPromptHandoffError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Authoritative final output failed handoff integrity validation",
            ) from exc

    def apply_scoped_user_correction(
        self, organization_id: UUID, correction: UserCorrection
    ) -> tuple[CorrectionReenrichmentResult, PromptEnrichmentWorkflowState]:
        request = UserCorrection.model_validate(correction)
        try:
            session = self.repository.get_design_session(request.session_id, organization_id)
            self._validate_session_artifacts(session)
            current = self.repository.get_current_revision(request.session_id, organization_id)
            cycles = self.repository.list_enrichment_cycles(request.session_id, organization_id)
            if not cycles:
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH,
                    "Correction requires an authoritative enrichment cycle",
                )
            answers = list_clarification_answer_results(
                self.repository,
                session_id=request.session_id,
                organization_id=organization_id,
            )
            corrections = list_user_correction_results(
                self.repository,
                session_id=request.session_id,
                organization_id=organization_id,
            )
            duplicate = _matching_correction(corrections, request)
            if duplicate is not None:
                return duplicate, self.get_current_state(request.session_id, organization_id)
            self._validate_parametric_lineage(cycles[-1].result)
            cycle_answers = _answers_after_cycle(cycles[-1], answers)
            _, previous_plan = self._restore_plan_for_cycle(
                request.session_id,
                organization_id,
                cycles[-1].enrichment_cycle_id,
            )
            result = process_user_correction(
                request,
                authoritative_session_id=request.session_id,
                current_revision=current,
                previous_cycle=cycles[-1],
                prior_answer_results=cycle_answers,
                dictionary=self.artifacts.dictionary,
                templates=self.artifacts.prompts,
                artifact_store=self.artifact_store,
                active_release=self.active_release,
                validation_report=self.validation_report,
                parametric_knowledge=self.artifacts.parametric_knowledge,
                created_at=self._clock(),
            )
            next_cycle_id = self._uuid()
            constraint_evidence = merge_constraint_evidence(
                result.post_transition_evaluation,
                session_id=request.session_id,
                organization_id=organization_id,
                source=request.source,
                authoritative_revision=result.authoritative_revision,
                enrichment_cycle_id=next_cycle_id,
                previous=previous_plan.constraint_evidence,
            )
            next_plan = plan_clarifications(
                result.authoritative_revision,
                result.post_transition_evaluation,
                role_id=session.role_id,
                dictionary=self.artifacts.dictionary,
                questions=self.artifacts.questions,
                rules=self.artifacts.rules,
                constraint_evidence=constraint_evidence,
            )
            commit_user_correction_result(
                self.repository,
                correction_record_id=self._uuid(),
                next_enrichment_cycle_id=next_cycle_id,
                organization_id=organization_id,
                expected_revision_id=request.expected_revision_id,
                result=result,
                created_at=self._clock(),
                next_clarification_plan_id=self._uuid(),
                next_clarification_plan=next_plan,
            )
            return result, self.get_current_state(request.session_id, organization_id)
        except PromptEnrichmentRuntimeError:
            raise
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Session was not found in organization scope",
            ) from exc
        except StaleRevisionError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.STALE_REVISION,
                "Product State revision changed during correction",
            ) from exc
        except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                "Pinned ACTIVE Knowledge release failed integrity verification",
            ) from exc
        except EnrichmentCycleConflictError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                "Concurrent Product State or enrichment-cycle update detected",
            ) from exc
        except CorrectionInputError as exc:
            code = (
                PromptEnrichmentRuntimeErrorCode.STALE_REVISION
                if exc.code == CorrectionErrorCode.STALE_REVISION
                else PromptEnrichmentRuntimeErrorCode.INVALID_CORRECTION
            )
            raise PromptEnrichmentRuntimeError(
                code,
                "Correction failed deterministic validation",
            ) from exc
        except UserCorrectionConflictError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.CORRECTION_CONFLICT,
                "Correction conflicts with durable history",
            ) from exc
        except UserCorrectionIntegrityError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Correction history failed integrity validation",
            ) from exc
        except ClarificationPlanIntegrityError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                "Correction clarification plan failed durable validation",
            ) from exc

    def apply_persisted_user_correction(
        self,
        organization_id: UUID,
        request: PersistedUserCorrectionRequest,
    ) -> tuple[CorrectionReenrichmentResult, PromptEnrichmentWorkflowState]:
        """Build a correction only from an organization-scoped persisted message."""

        request = PersistedUserCorrectionRequest.model_validate(request)
        try:
            session = self.repository.get_design_session(request.session_id, organization_id)
            message = self.repository.get_message(
                request.session_id, request.message_id, organization_id
            )
            cycles = self.repository.list_enrichment_cycles(request.session_id, organization_id)
            if not cycles:
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH,
                    "Correction requires an authoritative enrichment cycle",
                )
            latest = cycles[-1]
            pin = latest.release_pin
            correction = UserCorrection(
                session_id=request.session_id,
                expected_revision_id=request.expected_revision_id,
                correction_text=message.content,
                locale=session.locale,
                source=MessageSource(
                    message_id=str(message.message_id), recorded_at=_aware(message.created_at)
                ),
                previous_enrichment_cycle_id=latest.enrichment_cycle_id,
                previous_enrichment_cycle_number=latest.cycle_number,
                previous_enrichment_content_hash=latest.result.content_hash,
                knowledge_package_id=pin.package_id,
                knowledge_artifact_version=pin.artifact_version,
                knowledge_runtime_sha256=pin.runtime_sha256,
                knowledge_validation_report_sha256=pin.validation_report_sha256,
                dictionary_artifact_version=session.dictionary_artifact_version,
                prompt_template_artifact_version=session.prompt_artifact_version,
            )
            return self.apply_scoped_user_correction(organization_id, correction)
        except PromptEnrichmentRuntimeError:
            raise
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Session or correction message was not found in organization scope",
            ) from exc

    def record_clarification_answer(
        self,
        organization_id: UUID,
        plan: ClarificationPlan,
        answer: ClarificationAnswer,
        *,
        answer_record_id: UUID | None = None,
    ) -> tuple[ClarificationAnswerResult, PromptEnrichmentWorkflowState]:
        """Validate an answer, then atomically persist its revision and re-enrichment."""

        plan = ClarificationPlan.model_validate(plan)
        answer = ClarificationAnswer.model_validate(answer)
        try:
            session = self.repository.get_design_session(answer.session_id, organization_id)
            self._validate_session_artifacts(session)
            current = self.repository.get_current_revision(answer.session_id, organization_id)
            cycles = self.repository.list_enrichment_cycles(answer.session_id, organization_id)
            if not cycles:
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH,
                    "Clarification answer requires an authoritative enrichment cycle",
                )
            latest = cycles[-1]
            self._validate_parametric_lineage(latest.result)
            plan_records = self.repository.list_clarification_plans(
                answer.session_id, organization_id
            )
            plan_record = next(
                (item for item in plan_records if item.content_hash == plan.content_hash), None
            )
            if plan_record is None:
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                    "Clarification plan is not part of durable session history",
                )
            verified = self.repository.restore_pinned_knowledge_runtime(
                answer.session_id,
                organization_id,
                self.artifact_store,
                active_release=self.active_release,
                validation_report=self.validation_report,
            )
            previous = list_clarification_answer_results(
                self.repository,
                session_id=answer.session_id,
                organization_id=organization_id,
            )
            duplicate = next(
                (
                    item
                    for item in previous
                    if item.plan_content_hash == answer.plan_content_hash
                    and item.clarification_id == answer.clarification_id
                ),
                None,
            )
            if duplicate is not None:
                if duplicate.answer_hash != _hash(answer.model_dump(mode="json")):
                    raise PromptEnrichmentRuntimeError(
                        PromptEnrichmentRuntimeErrorCode.CLARIFICATION_CONFLICT,
                        "Clarification question already has a different durable decision",
                    )
                state = self.get_current_state(answer.session_id, organization_id)
                return duplicate, state.model_copy(
                    update={"status": PromptEnrichmentWorkflowStatus.CLARIFICATION_ANSWER_RECORDED}
                )
            result = process_clarification_answer(
                plan,
                answer,
                authoritative_session_id=answer.session_id,
                current_revision=current,
                active_release=verified,
                dictionary=self.artifacts.dictionary,
                questions=self.artifacts.questions,
                rules=self.artifacts.rules,
                created_at=self._clock(),
                previous_results=previous,
            )
            next_cycle_id = self._uuid()
            if result.resulting_revision is not None:
                proposals = tuple(item.proposal for item in latest.result.decisions)
                next_enrichment = enrich_prompt_with_active_release(
                    result.resulting_revision,
                    self.artifacts.prompts,
                    self.artifact_store,
                    knowledge_package_id=latest.release_pin.package_id,
                    knowledge_artifact_version=latest.release_pin.artifact_version,
                    active_release=verified,
                    validation_report=self.validation_report,
                    proposals=proposals,
                    **self._parametric_kwargs(result.resulting_revision),
                )
                authoritative = result.resulting_revision
            else:
                next_enrichment = latest.result
                authoritative = current
            answered_ids = tuple(item.clarification_id for item in previous) + (
                result.clarification_id,
            )
            next_plan = continue_clarification_plan(
                plan,
                authoritative,
                answered_clarification_ids=answered_ids,
                questions=self.artifacts.questions,
                rules=self.artifacts.rules,
            )
            commit_clarification_answer_result(
                self.repository,
                answer_record_id=answer_record_id or self._uuid(),
                clarification_plan_id=plan_record.clarification_plan_id,
                organization_id=organization_id,
                expected_revision_id=answer.expected_revision_id,
                result=result,
                created_at=self._clock(),
                next_enrichment_cycle_id=next_cycle_id,
                next_enrichment_result=next_enrichment,
                next_clarification_plan_id=self._uuid(),
                next_clarification_plan=next_plan,
            )
            state = self.get_current_state(answer.session_id, organization_id)
            return result, state.model_copy(
                update={"status": PromptEnrichmentWorkflowStatus.CLARIFICATION_ANSWER_RECORDED}
            )
        except PromptEnrichmentRuntimeError:
            raise
        except ClarificationAnswerError as exc:
            mapped = {
                ClarificationAnswerErrorCode.INVALID_DECISION: (
                    PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_DECISION
                ),
                ClarificationAnswerErrorCode.INVALID_OPTION: (
                    PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_OPTION
                ),
                ClarificationAnswerErrorCode.STALE_REVISION: (
                    PromptEnrichmentRuntimeErrorCode.STALE_REVISION
                ),
                ClarificationAnswerErrorCode.PLAN_MISMATCH: (
                    PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN
                ),
                ClarificationAnswerErrorCode.INVALID_PLAN: (
                    PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN
                ),
            }.get(exc.code, PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_ANSWER)
            raise PromptEnrichmentRuntimeError(
                mapped,
                "Clarification answer failed deterministic validation",
            ) from exc
        except ClarificationDecisionConflictError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.CLARIFICATION_CONFLICT,
                "Clarification decision conflicts with durable history",
            ) from exc
        except (ClarificationDecisionIntegrityError, EnrichmentIntegrityError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Clarification or enrichment history failed integrity validation",
            ) from exc
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Session was not found in organization scope",
            ) from exc
        except StaleRevisionError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.STALE_REVISION,
                "Product State revision changed during clarification answer",
            ) from exc
        except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                "Pinned ACTIVE Knowledge release failed integrity verification",
            ) from exc
        except EnrichmentCycleConflictError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                "Concurrent Product State or enrichment-cycle update detected",
            ) from exc
        except ClarificationPlanIntegrityError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                "Clarification plan failed durable validation",
            ) from exc

    def record_persisted_clarification_answer(
        self,
        organization_id: UUID,
        request: PersistedClarificationAnswerRequest,
    ) -> tuple[ClarificationAnswerResult, PromptEnrichmentWorkflowState]:
        """Restore the authoritative plan and process a bounded client decision."""

        request = PersistedClarificationAnswerRequest.model_validate(request)
        try:
            plan = self.restore_clarification_plan(
                request.session_id,
                organization_id,
                request.clarification_plan_id,
                require_current=False,
            )
            message = self.repository.get_message(
                request.session_id, request.message_id, organization_id
            )
            answer = ClarificationAnswer(
                session_id=request.session_id,
                plan_content_hash=plan.content_hash,
                clarification_id=request.clarification_id,
                decision=request.decision,
                selected_option=request.selected_option,
                expected_revision_id=request.expected_revision_id,
                knowledge_package_id=plan.knowledge_package_id,
                knowledge_artifact_version=plan.knowledge_artifact_version,
                knowledge_runtime_sha256=plan.knowledge_runtime_sha256,
                knowledge_validation_report_sha256=(plan.knowledge_validation_report_sha256),
                source=MessageSource(
                    message_id=str(message.message_id), recorded_at=_aware(message.created_at)
                ),
            )
            previous = list_clarification_answer_results(
                self.repository,
                session_id=request.session_id,
                organization_id=organization_id,
            )
            duplicate = next(
                (
                    item
                    for item in previous
                    if item.plan_content_hash == plan.content_hash
                    and item.clarification_id == request.clarification_id
                ),
                None,
            )
            if duplicate is not None:
                if duplicate.answer_hash != _hash(answer.model_dump(mode="json")):
                    raise PromptEnrichmentRuntimeError(
                        PromptEnrichmentRuntimeErrorCode.CLARIFICATION_CONFLICT,
                        "Clarification question already has a different durable decision",
                    )
                state = self.get_current_state(request.session_id, organization_id)
                return duplicate, state.model_copy(
                    update={"status": PromptEnrichmentWorkflowStatus.CLARIFICATION_ANSWER_RECORDED}
                )
            self.restore_clarification_plan(
                request.session_id,
                organization_id,
                request.clarification_plan_id,
                require_current=True,
            )
            return self.record_clarification_answer(
                organization_id,
                plan,
                answer,
                answer_record_id=request.answer_id,
            )
        except PromptEnrichmentRuntimeError:
            raise
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Session, plan, or answer message was not found in organization scope",
            ) from exc

    def restore_clarification_plan(
        self,
        session_id: UUID,
        organization_id: UUID,
        clarification_plan_id: UUID,
        *,
        require_current: bool,
    ) -> ClarificationPlan:
        """Restore and verify an immutable plan without rerunning clarification planning."""

        try:
            session = self.repository.get_design_session(session_id, organization_id)
            self._validate_session_artifacts(session)
            record = self.repository.get_clarification_plan(
                session_id, clarification_plan_id, organization_id
            )
            cycle = self.repository.get_enrichment_cycle(
                session_id, record.enrichment_cycle_id, organization_id
            )
            plan = ClarificationPlan.model_validate(record.plan_payload)
            if (
                record.content_hash != plan.content_hash
                or record.specification_revision_id != cycle.specification_revision_id
                or plan.design_revision_id != str(cycle.specification_revision_id)
                or plan.knowledge_package_id != cycle.release_pin.package_id
                or plan.knowledge_artifact_version != cycle.release_pin.artifact_version
                or plan.knowledge_runtime_sha256 != cycle.release_pin.runtime_sha256
                or plan.knowledge_validation_report_sha256
                != cycle.release_pin.validation_report_sha256
                or plan.question_artifact_version != session.question_artifact_version
                or plan.rules_artifact_version != session.rules_artifact_version
            ):
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                    "Clarification plan lineage failed integrity validation",
                )
            verified = self.repository.restore_pinned_knowledge_runtime(
                session_id,
                organization_id,
                self.artifact_store,
                active_release=self.active_release,
                validation_report=self.validation_report,
            )
            if (
                verified.runtime_sha256 != plan.knowledge_runtime_sha256
                or verified.validation_report_sha256 != plan.knowledge_validation_report_sha256
            ):
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                    "Clarification plan release is not the verified session release",
                )
            for question in plan.questions:
                catalog_question = self.artifacts.questions.get_question(
                    question.semantic_question_id
                )
                if (
                    question.design_revision_id != plan.design_revision_id
                    or question.target != catalog_question.target
                    or question.question_artifact_version != plan.question_artifact_version
                    or question.rules_artifact_version != plan.rules_artifact_version
                ):
                    raise PromptEnrichmentRuntimeError(
                        PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                        "Clarification question lineage failed integrity validation",
                    )
            for evidence in plan.constraint_evidence:
                if evidence.session_id != session_id or evidence.organization_id != organization_id:
                    raise PromptEnrichmentRuntimeError(
                        PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                        "Constraint evidence belongs to another session scope",
                    )
                self.repository.get_enrichment_cycle(
                    session_id, evidence.source_enrichment_cycle_id, organization_id
                )
                self.repository.get_revision(
                    session_id, evidence.source_revision_id, organization_id
                )
            answers = list_clarification_answer_results(
                self.repository, session_id=session_id, organization_id=organization_id
            )
            question_ids = {item.clarification_id for item in plan.questions}
            if any(
                item.plan_content_hash == plan.content_hash
                and item.clarification_id not in question_ids
                for item in answers
            ):
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                    "Clarification decisions do not match their durable plan",
                )
            if require_current:
                cycles = self.repository.list_enrichment_cycles(session_id, organization_id)
                if (
                    not cycles
                    or cycles[-1].enrichment_cycle_id != record.enrichment_cycle_id
                    or session.current_revision_id != record.specification_revision_id
                ):
                    raise PromptEnrichmentRuntimeError(
                        PromptEnrichmentRuntimeErrorCode.STALE_CLARIFICATION_PLAN,
                        "Clarification plan is historical and no longer actionable",
                    )
            return plan
        except PromptEnrichmentRuntimeError:
            raise
        except (OwnershipMismatchError, NotFoundError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND,
                "Clarification plan was not found in organization scope",
            ) from exc
        except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                "Pinned ACTIVE Knowledge release failed integrity verification",
            ) from exc
        except (ClarificationPlanIntegrityError, ValueError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN,
                "Clarification plan failed integrity validation",
            ) from exc

    def _restore_plan_for_cycle(self, session_id, organization_id, enrichment_cycle_id):
        try:
            record = self.repository.get_clarification_plan_for_cycle(
                session_id, enrichment_cycle_id, organization_id
            )
        except NotFoundError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Authoritative enrichment cycle has no durable clarification plan",
            ) from exc
        plan = self.restore_clarification_plan(
            session_id,
            organization_id,
            record.clarification_plan_id,
            require_current=False,
        )
        return record.clarification_plan_id, plan

    def _evaluate(self, revision, parsed, source):
        return enrich_parsed_candidates_with_active_release(
            revision,
            parse_result=parsed,
            source=source,
            dictionary=self.artifacts.dictionary,
            templates=self.artifacts.prompts,
            artifact_store=self.artifact_store,
            knowledge_package_id=self.knowledge_package_id,
            knowledge_artifact_version=self.knowledge_artifact_version,
            active_release=self.active_release,
            validation_report=self.validation_report,
            **self._parametric_kwargs(revision),
        )

    def _parametric_kwargs(self, revision):
        catalog = self.artifacts.parametric_knowledge
        return {
            "parametric_catalog_id": catalog.catalog_id,
            "parametric_artifact_version": str(catalog.artifact_version),
            "parametric_catalog_sha256": catalog.sha256,
            "parametric_references": select_parametric_references(revision, catalog),
        }

    def _validate_parametric_lineage(self, result):
        catalog = self.artifacts.parametric_knowledge
        expected = (
            catalog.catalog_id,
            str(catalog.artifact_version),
            catalog.sha256,
        )
        actual = (
            result.parametric_catalog_id,
            result.parametric_artifact_version,
            result.parametric_catalog_sha256,
        )
        if actual != expected:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.ARTIFACT_MISMATCH,
                "Parametric Knowledge catalog does not match durable enrichment lineage",
            )

    def _load_release(self):
        return self.artifact_store.load_active_runtime(
            self.knowledge_package_id,
            self.knowledge_artifact_version,
            active_release=self.active_release,
            validation_report=self.validation_report,
        )

    def _validate_session_artifacts(self, session):
        expected = (
            self.artifacts.versions.roles,
            self.artifacts.versions.dictionary,
            self.artifacts.versions.questions,
            self.artifacts.versions.rules,
            self.artifacts.versions.prompts,
        )
        actual = (
            session.role_artifact_version,
            session.dictionary_artifact_version,
            session.question_artifact_version,
            session.rules_artifact_version,
            session.prompt_artifact_version,
        )
        if actual != expected:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.ARTIFACT_MISMATCH,
                "Session artifact pins do not match the supplied runtime artifacts",
            )

    def _state_from_cycle(
        self,
        *,
        session_id,
        organization_id,
        cycle,
        clarification_plan_id,
        clarification_plan,
    ):
        snapshot = build_final_prompt_snapshot(
            self.repository,
            session_id=session_id,
            organization_id=organization_id,
            artifacts=self.artifacts,
            artifact_store=self.artifact_store,
            active_release=self.active_release,
            validation_report=self.validation_report,
        )
        try:
            assembly = assemble_internal_final_prompt(
                snapshot,
                dictionary=self.artifacts.dictionary,
                templates=self.artifacts.prompts,
            )
        except FinalPromptInputError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Durable state cannot form a consistent final-prompt snapshot",
            ) from exc
        status = _workflow_status(assembly, clarification_plan)
        record = self.repository.get_clarification_plan_for_cycle(
            session_id, snapshot.enrichment_cycle_id, organization_id
        )
        if (
            record.clarification_plan_id != clarification_plan_id
            or cycle.enrichment_cycle_id != snapshot.enrichment_cycle_id
        ):
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                "Enrichment state changed during restoration",
            )
        source, gate = self._preparation_context(
            self.repository, snapshot, assembly, record, clarification_plan
        )
        from .generation_preparations import preparation_expectations

        try:
            render_semantic_source(source, gate)
            can_prepare = True
        except GenerationPreparationError:
            can_prepare = False
        return PromptEnrichmentWorkflowState(
            session_id=session_id,
            organization_id=organization_id,
            authoritative_revision_id=snapshot.revision.revision_id,
            enrichment_cycle_id=cycle.enrichment_cycle_id,
            enrichment_cycle_number=cycle.cycle_number,
            knowledge_release=snapshot.knowledge_release,
            status=status,
            clarification_plan_id=clarification_plan_id,
            clarification_plan=clarification_plan,
            final_output=assembly,
            preparation_expectations=preparation_expectations(source, gate),
            can_prepare=can_prepare,
        )


def build_final_prompt_snapshot(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    organization_id: UUID,
    artifacts: RuntimeArtifacts,
    artifact_store: KnowledgeArtifactStore,
    active_release: ActiveKnowledgeRuntime | object,
    validation_report: ProductionValidationReport | object,
) -> FinalPromptSnapshot:
    """Restore one consistent organization-scoped durable snapshot for Step #12."""

    session = repository.get_design_session(session_id, organization_id)
    revision = repository.get_current_revision(session_id, organization_id)
    cycles = repository.list_enrichment_cycles(session_id, organization_id)
    if not cycles:
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH,
            "Session has no durable enrichment cycle",
        )
    latest = cycles[-1]
    if latest.specification_revision_id != revision.revision_id:
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH,
            "Latest enrichment cycle does not match current Product State",
        )
    verified = repository.restore_pinned_knowledge_runtime(
        session_id,
        organization_id,
        artifact_store,
        active_release=active_release,
        validation_report=validation_report,
    )
    pin = latest.release_pin
    if (
        verified.runtime_sha256 != pin.runtime_sha256
        or verified.validation_report_sha256 != pin.validation_report_sha256
    ):
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
            "Verified Knowledge runtime does not match durable cycle lineage",
        )
    catalog = artifacts.parametric_knowledge
    actual_parametric = (
        latest.result.parametric_catalog_id,
        latest.result.parametric_artifact_version,
        latest.result.parametric_catalog_sha256,
    )
    expected_parametric = (
        catalog.catalog_id,
        str(catalog.artifact_version),
        catalog.sha256,
    )
    if actual_parametric != expected_parametric:
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.ARTIFACT_MISMATCH,
            "Parametric Knowledge catalog does not match durable enrichment lineage",
        )
    expected_artifacts = (
        artifacts.versions.roles,
        artifacts.versions.dictionary,
        artifacts.versions.questions,
        artifacts.versions.rules,
        artifacts.versions.prompts,
    )
    session_artifacts = (
        session.role_artifact_version,
        session.dictionary_artifact_version,
        session.question_artifact_version,
        session.rules_artifact_version,
        session.prompt_artifact_version,
    )
    if session_artifacts != expected_artifacts:
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.ARTIFACT_MISMATCH,
            "Session artifact pins do not match snapshot artifacts",
        )
    answers = list_clarification_answer_results(
        repository, session_id=session_id, organization_id=organization_id
    )
    corrections = list_user_correction_results(
        repository, session_id=session_id, organization_id=organization_id
    )
    try:
        plan_record = repository.get_clarification_plan_for_cycle(
            session_id, latest.enrichment_cycle_id, organization_id
        )
        plan = ClarificationPlan.model_validate(plan_record.plan_payload)
    except (NotFoundError, ClarificationPlanIntegrityError, ValueError) as exc:
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
            "Latest enrichment cycle has no compatible durable constraint evidence",
        ) from exc
    if (
        plan_record.content_hash != plan.content_hash
        or plan.design_revision_id != str(revision.revision_id)
        or plan.knowledge_package_id != pin.package_id
        or plan.knowledge_artifact_version != pin.artifact_version
        or plan.knowledge_runtime_sha256 != pin.runtime_sha256
        or plan.knowledge_validation_report_sha256 != pin.validation_report_sha256
    ):
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
            "Durable constraint evidence lineage does not match the authoritative cycle",
        )
    for evidence in plan.constraint_evidence:
        try:
            repository.get_enrichment_cycle(
                session_id, evidence.source_enrichment_cycle_id, organization_id
            )
            repository.get_revision(session_id, evidence.source_revision_id, organization_id)
        except (NotFoundError, OwnershipMismatchError) as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Constraint evidence references invalid session history",
            ) from exc
    correction_blocks = _effective_correction_blocks(
        repository,
        session_id=session_id,
        organization_id=organization_id,
        cycles=cycles,
        corrections=corrections,
        answers=answers,
        current_plan=plan,
        artifacts=artifacts,
    )
    lineage = _decision_lineage(
        session_id, revision.revision_id, answers, corrections, correction_blocks
    )
    return FinalPromptSnapshot(
        session_id=session_id,
        organization_id=organization_id,
        locale=session.locale,
        revision=revision,
        enrichment_cycle_id=latest.enrichment_cycle_id,
        latest_enrichment_cycle_id=latest.enrichment_cycle_id,
        enrichment_cycle_number=latest.cycle_number,
        enrichment_result=latest.result,
        knowledge_release=KnowledgeReleaseReference(
            package_id=pin.package_id,
            artifact_version=pin.artifact_version,
            runtime_sha256=pin.runtime_sha256,
            validation_report_sha256=pin.validation_report_sha256,
        ),
        artifact_versions=FinalPromptArtifactVersions(
            design_schema_version=session.design_schema_version,
            dictionary_artifact_version=session.dictionary_artifact_version,
            question_artifact_version=session.question_artifact_version,
            rules_artifact_version=session.rules_artifact_version,
            prompt_template_artifact_version=session.prompt_artifact_version,
            enrichment_version=latest.result.enrichment_version,
        ),
        rule_decision=artifacts.rules.evaluate(revision, session.role_id),
        decision_lineage=lineage,
        constraint_evidence=plan.constraint_evidence,
    )


def _effective_correction_blocks(
    repository,
    *,
    session_id,
    organization_id,
    cycles,
    corrections,
    answers,
    current_plan,
    artifacts,
):
    """Project open correction obligations; never rewrite their immutable outcomes.

    A question can discharge only its own source candidates along answer-only plan
    continuations. A correction starts fresh parsing, so matching candidate IDs or
    targets across that boundary is deliberately insufficient proof of resolution.
    """
    if not any(item.outcome == CorrectionOutcome.DEFERRED for item in corrections):
        return {item.content_hash: False for item in corrections}
    by_cycle = {cycle.enrichment_cycle_id: cycle for cycle in cycles}
    plans = {}
    try:
        records = repository.list_clarification_plans(session_id, organization_id)
        for record in records:
            cycle = by_cycle[record.enrichment_cycle_id]
            restored = ClarificationPlan.model_validate(record.plan_payload)
            if (
                record.content_hash != restored.content_hash
                or record.specification_revision_id != cycle.specification_revision_id
                or restored.design_revision_id != str(cycle.specification_revision_id)
                or restored.knowledge_package_id != cycle.release_pin.package_id
                or restored.knowledge_artifact_version != cycle.release_pin.artifact_version
                or restored.knowledge_runtime_sha256 != cycle.release_pin.runtime_sha256
                or restored.knowledge_validation_report_sha256
                != cycle.release_pin.validation_report_sha256
                or restored.question_artifact_version != current_plan.question_artifact_version
                or restored.rules_artifact_version != current_plan.rules_artifact_version
                or restored.role_id != current_plan.role_id
                or restored.locale != current_plan.locale
            ):
                raise ValueError("historical clarification plan lineage mismatch")
            plans[record.clarification_plan_id] = (cycle, restored)
        answer_plans = {
            record.content_hash: plans[record.clarification_plan_id]
            for record in repository.list_clarification_answers(session_id, organization_id)
            if record.clarification_plan_id is not None
        }
    except (KeyError, ValueError, ClarificationPlanIntegrityError) as exc:
        raise PromptEnrichmentRuntimeError(
            PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
            "Effective readiness requires valid durable clarification lineage",
        ) from exc
    correction_cycles = {item.next_enrichment_cycle_number for item in corrections}
    by_number = {cycle.cycle_number: cycle for cycle in cycles}
    plans_by_number = {cycle.cycle_number: plan for cycle, plan in plans.values()}
    answer_steps = set()
    for answer in answers:
        bound = answer_plans.get(answer.content_hash)
        if bound is None:
            continue
        source_cycle, source_plan = bound
        successor = by_number.get(source_cycle.cycle_number + 1)
        successor_plan = plans_by_number.get(source_cycle.cycle_number + 1)
        if successor is None or successor.specification_revision_id != (
            answer.new_revision_id or answer.previous_revision_id
        ):
            continue
        next_revision = repository.get_revision(
            session_id, successor.specification_revision_id, organization_id
        )
        expected_plan = continue_clarification_plan(
            source_plan,
            next_revision,
            answered_clarification_ids=(answer.clarification_id,),
            questions=artifacts.questions,
            rules=artifacts.rules,
        )
        if expected_plan == successor_plan:
            # Exact existing continuation semantics also prove nonmutating
            # SKIP/UNKNOWN/REJECT steps; a coincidentally newer revision cannot.
            answer_steps.add(source_cycle.cycle_number)
    flags = {}
    for correction in corrections:
        blocks = correction.outcome == CorrectionOutcome.DEFERRED
        if blocks and correction.reason != CorrectionReason.REVISION_TRANSITION_DEFERRED:
            origin = next(
                (
                    item
                    for item in plans.values()
                    if item[0].cycle_number == correction.next_enrichment_cycle_number
                ),
                None,
            )
            if origin is not None:
                cycle, original_plan = origin
                resolved = {
                    evidence.source_candidate_id
                    for evidence in current_plan.constraint_evidence
                    if evidence.source == correction.source
                    and evidence.source_enrichment_cycle_id == cycle.enrichment_cycle_id
                    and evidence.source_revision_id == cycle.specification_revision_id
                    and evidence.status in {"active", "superseded"}
                    and any(
                        candidate.candidate_id == evidence.source_candidate_id
                        and candidate.semantic_subject == evidence.semantic_subject
                        and candidate.classification.value == evidence.kind
                        and candidate.evidence.start == evidence.source_span_start
                        and candidate.evidence.end == evidence.source_span_end
                        for candidate in correction.parsed_correction.candidates
                    )
                }
                for question in original_plan.questions:
                    if any(
                        _answer_discharges_question(
                            answer,
                            question,
                            origin=cycle.cycle_number,
                            answer_plan=answer_plans.get(answer.content_hash),
                            correction_cycles=correction_cycles,
                            answer_steps=answer_steps,
                        )
                        for answer in answers
                    ):
                        resolved.update(question.source_candidate_ids)
                dispositions = correction.correction_evaluation.dispositions
                noncritical = {
                    item.candidate_id
                    for item in original_plan.unasked_evidence
                    if item.reason == UnaskedReason.NONCRITICAL_UNKNOWN
                }
                pending = {
                    item.candidate.candidate_id
                    for item in dispositions
                    if item.outcome == CandidateDispositionOutcome.DEFERRED
                }
                # Ignore only source-overlap mirrors of a separately discharged or
                # already-current Dictionary fact, not arbitrary Knowledge-only terms.
                for item in dispositions:
                    candidate = item.candidate
                    if candidate.normalization_source.value != "knowledge_library":
                        continue
                    if any(
                        other.candidate.normalization_source.value == "domain_dictionary"
                        and other.candidate.evidence == candidate.evidence
                        and other.candidate.target == candidate.target
                        and other.candidate.subject == candidate.subject
                        and other.candidate.normalized_values == candidate.normalized_values
                        and (
                            other.candidate.candidate_id in resolved
                            or other.reason == CandidateDispositionReason.ALREADY_CURRENT
                        )
                        for other in dispositions
                    ):
                        resolved.add(candidate.candidate_id)
                has_nonmutating_fact = any(
                    item.reason
                    in {
                        CandidateDispositionReason.ALREADY_CURRENT,
                        CandidateDispositionReason.PRESERVATION_RETAINED,
                    }
                    for item in dispositions
                )
                blocks = bool(pending - resolved - noncritical) or not (
                    resolved or has_nonmutating_fact
                )
        flags[correction.content_hash] = blocks
    return flags


def _answer_discharges_question(
    answer, question, *, origin, answer_plan, correction_cycles, answer_steps
):
    if answer_plan is None:
        return False  # Legacy unbound answers cannot prove causal resolution.
    cycle, plan = answer_plan
    if cycle.cycle_number < origin or any(
        origin < number <= cycle.cycle_number for number in correction_cycles
    ):
        return False
    if any(number not in answer_steps for number in range(origin, cycle.cycle_number)):
        return False  # A newer revision alone is not proof of answer continuation.
    linked = next(
        (item for item in plan.questions if item.clarification_id == answer.clarification_id), None
    )
    if linked is None or answer.plan_content_hash != plan.content_hash:
        return False
    excluded = {"clarification_id", "design_revision_id"}
    if (
        linked.model_dump(exclude=excluded) != question.model_dump(exclude=excluded)
        or answer.target != question.target.value
        or answer.subject != (question.subject.value if question.subject is not None else None)
        or answer.source_candidate_ids != question.source_candidate_ids
        or answer.source_proposal_ids != question.source_proposal_ids
        or answer.evidence != question.evidence
    ):
        return False
    return answer.question_resolved or (
        question.importance != ClarificationImportance.BLOCKING
        and not answer.blocks_progression
        and answer.decision in {ClarificationDecision.SKIP, ClarificationDecision.UNKNOWN}
    )


def _decision_lineage(session_id, current_revision_id, answers, corrections, correction_blocks):
    items = []
    for answer in answers:
        option = answer.selected_option.value if answer.selected_option is not None else None
        items.append(
            FinalPromptDecisionLineage(
                kind="clarification",
                session_id=session_id,
                decision_id=answer.clarification_id,
                decision=answer.decision.value,
                outcome=answer.outcome.value,
                target=answer.target,
                selected_value=option,
                source_revision_id=answer.previous_revision_id,
                resulting_revision_id=answer.new_revision_id,
                applies_to_revision_id=current_revision_id,
                knowledge_package_id=answer.knowledge_package_id,
                knowledge_artifact_version=answer.knowledge_artifact_version,
                knowledge_runtime_sha256=answer.knowledge_runtime_sha256,
                knowledge_validation_report_sha256=answer.knowledge_validation_report_sha256,
                question_artifact_version=answer.question_artifact_version,
                rules_artifact_version=answer.rules_artifact_version,
                blocks_progression=answer.blocks_progression,
                content_hash=answer.content_hash,
            )
        )
    for correction in corrections:
        items.append(
            FinalPromptDecisionLineage(
                kind="correction",
                session_id=session_id,
                decision_id=str(correction.source.message_id),
                decision="CORRECT",
                outcome=correction.outcome.value,
                source_revision_id=correction.previous_revision_id,
                resulting_revision_id=correction.new_revision_id,
                applies_to_revision_id=current_revision_id,
                knowledge_package_id=correction.knowledge_package_id,
                knowledge_artifact_version=correction.knowledge_artifact_version,
                knowledge_runtime_sha256=correction.knowledge_runtime_sha256,
                knowledge_validation_report_sha256=(correction.knowledge_validation_report_sha256),
                blocks_progression=correction_blocks[correction.content_hash],
                content_hash=correction.content_hash,
            )
        )
    return tuple(sorted(items, key=lambda item: (item.kind, item.decision_id, item.content_hash)))


def _workflow_status(assembly, clarification_plan):
    readiness = assembly.internal_final_prompt.readiness
    if clarification_plan is not None:
        if any(
            item.importance == ClarificationImportance.BLOCKING
            for item in clarification_plan.questions
        ):
            return PromptEnrichmentWorkflowStatus.BLOCKING_CLARIFICATION_UNRESOLVED
    if readiness == FinalPromptReadiness.BLOCKED:
        return PromptEnrichmentWorkflowStatus.FINAL_OUTPUT_BLOCKED
    if clarification_plan is not None:
        if clarification_plan.questions:
            return PromptEnrichmentWorkflowStatus.CLARIFICATION_AVAILABLE
    if readiness == FinalPromptReadiness.READY:
        return PromptEnrichmentWorkflowStatus.FINAL_OUTPUT_READY
    if readiness == FinalPromptReadiness.READY_WITH_UNRESOLVED:
        return PromptEnrichmentWorkflowStatus.FINAL_OUTPUT_READY_WITH_UNRESOLVED
    return PromptEnrichmentWorkflowStatus.FINAL_OUTPUT_BLOCKED


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _hash(payload) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _matching_correction(corrections, request):
    for item in corrections:
        if (
            item.source.kind == request.source.kind
            and item.source.message_id == request.source.message_id
        ):
            if (
                item.source != request.source
                or item.correction_text != request.correction_text
                or item.locale != request.locale
                or item.previous_revision_id != request.expected_revision_id
                or item.previous_enrichment_cycle_id != request.previous_enrichment_cycle_id
                or item.previous_enrichment_cycle_number != request.previous_enrichment_cycle_number
                or item.previous_enrichment_content_hash != request.previous_enrichment_content_hash
                or item.knowledge_package_id != request.knowledge_package_id
                or item.knowledge_artifact_version != request.knowledge_artifact_version
                or item.knowledge_runtime_sha256 != request.knowledge_runtime_sha256
                or item.knowledge_validation_report_sha256
                != request.knowledge_validation_report_sha256
                or item.dictionary_artifact_version != request.dictionary_artifact_version
                or item.prompt_template_artifact_version != request.prompt_template_artifact_version
            ):
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.CORRECTION_CONFLICT,
                    "Correction source already has different durable semantics",
                )
            return item
    return None


def _answers_after_cycle(cycle, answers):
    """Return only decisions not already represented by the selected enrichment cycle."""

    cursor = cycle.specification_revision_id
    selected = []
    for answer in answers:
        if answer.previous_revision_id != cursor:
            continue
        selected.append(answer)
        if answer.new_revision_id is not None:
            cursor = answer.new_revision_id
    return tuple(selected)
