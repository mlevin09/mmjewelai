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
from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)
from jewelai_domain.models import ImmutableModel, MessageSource
from jewelai_domain.revisions import RevisionConflict, revise_design
from jewelai_parser import FullMessageParseResult, ParserProposal, parse_full_message
from jewelai_persistence import (
    ClarificationDecisionConflictError,
    ClarificationDecisionIntegrityError,
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
    FinalPromptArtifactVersions,
    FinalPromptAssembly,
    FinalPromptDecisionLineage,
    FinalPromptInputError,
    FinalPromptReadiness,
    FinalPromptSnapshot,
    KnowledgeReleaseReference,
    assemble_internal_final_prompt,
    enrich_prompt_with_active_release,
)

from .artifacts import RuntimeArtifacts
from .clarification import ClarificationImportance, ClarificationPlan, plan_clarifications
from .clarification_answers import (
    ClarificationAnswer,
    ClarificationAnswerError,
    ClarificationAnswerResult,
    process_clarification_answer,
)
from .correction_enrichment import (
    CorrectionInputError,
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
from .parsed_enrichment import (
    ParsedCandidateEnrichmentResult,
    enrich_parsed_candidates_with_active_release,
)


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
    CLARIFICATION_CONFLICT = "clarification_conflict"
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


class PromptEnrichmentWorkflowState(ImmutableModel):
    session_id: UUID
    organization_id: UUID
    authoritative_revision_id: UUID
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int
    knowledge_release: KnowledgeReleaseReference
    status: PromptEnrichmentWorkflowStatus
    clarification_plan: ClarificationPlan | None = None
    final_output: FinalPromptAssembly | None = None


class InitialEnrichmentRuntimeResult(ImmutableModel):
    parse_result: FullMessageParseResult
    parser_proposal: ParserProposal
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
            cycle = self.repository.commit_initial_enrichment(
                enrichment_cycle_id=self._uuid(),
                session_id=request.session_id,
                organization_id=request.organization_id,
                expected_revision_id=request.expected_revision_id,
                resulting_revision=resulting_revision,
                result=enrichment.enrichment_result,
                created_at=self._clock(),
            )
            clarification = plan_clarifications(
                authoritative,
                enrichment,
                role_id=session.role_id,
                dictionary=self.artifacts.dictionary,
                questions=self.artifacts.questions,
                rules=self.artifacts.rules,
            )
            workflow = self._state_from_cycle(
                session_id=request.session_id,
                organization_id=request.organization_id,
                cycle=cycle,
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
            return self._state_from_cycle(
                session_id=session_id,
                organization_id=organization_id,
                cycle=cycles[-1],
                clarification_plan=None,
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
        except EnrichmentIntegrityError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_HISTORY,
                "Durable enrichment history failed integrity verification",
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
            result = process_user_correction(
                request,
                authoritative_session_id=request.session_id,
                current_revision=current,
                previous_cycle=cycles[-1],
                prior_answer_results=answers,
                dictionary=self.artifacts.dictionary,
                templates=self.artifacts.prompts,
                artifact_store=self.artifact_store,
                active_release=self.active_release,
                validation_report=self.validation_report,
                created_at=self._clock(),
            )
            commit_user_correction_result(
                self.repository,
                correction_record_id=self._uuid(),
                next_enrichment_cycle_id=self._uuid(),
                organization_id=organization_id,
                expected_revision_id=request.expected_revision_id,
                result=result,
                created_at=self._clock(),
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
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_CORRECTION,
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

    def record_clarification_answer(
        self,
        organization_id: UUID,
        plan: ClarificationPlan,
        answer: ClarificationAnswer,
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
            next_cycle_id = None
            next_enrichment = None
            if result.resulting_revision is not None:
                next_cycle_id = self._uuid()
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
                )
            commit_clarification_answer_result(
                self.repository,
                answer_record_id=self._uuid(),
                organization_id=organization_id,
                expected_revision_id=answer.expected_revision_id,
                result=result,
                created_at=self._clock(),
                next_enrichment_cycle_id=next_cycle_id,
                next_enrichment_result=next_enrichment,
            )
            state = self.get_current_state(answer.session_id, organization_id)
            return result, state.model_copy(
                update={"status": PromptEnrichmentWorkflowStatus.CLARIFICATION_ANSWER_RECORDED}
            )
        except PromptEnrichmentRuntimeError:
            raise
        except ClarificationAnswerError as exc:
            raise PromptEnrichmentRuntimeError(
                PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_ANSWER,
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

    def _state_from_cycle(self, *, session_id, organization_id, cycle, clarification_plan):
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
        return PromptEnrichmentWorkflowState(
            session_id=session_id,
            organization_id=organization_id,
            authoritative_revision_id=snapshot.revision.revision_id,
            enrichment_cycle_id=cycle.enrichment_cycle_id,
            enrichment_cycle_number=cycle.cycle_number,
            knowledge_release=snapshot.knowledge_release,
            status=status,
            clarification_plan=clarification_plan,
            final_output=assembly,
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
    lineage = _decision_lineage(session_id, revision.revision_id, answers, corrections)
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
    )


def _decision_lineage(session_id, current_revision_id, answers, corrections):
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
                blocks_progression=correction.outcome.value == "DEFERRED",
                content_hash=correction.content_hash,
            )
        )
    return tuple(sorted(items, key=lambda item: (item.kind, item.decision_id, item.content_hash)))


def _workflow_status(assembly, clarification_plan):
    if clarification_plan is not None:
        if any(
            item.importance == ClarificationImportance.BLOCKING
            for item in clarification_plan.questions
        ):
            return PromptEnrichmentWorkflowStatus.BLOCKING_CLARIFICATION_UNRESOLVED
        if clarification_plan.questions:
            return PromptEnrichmentWorkflowStatus.CLARIFICATION_AVAILABLE
    readiness = assembly.internal_final_prompt.readiness
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
