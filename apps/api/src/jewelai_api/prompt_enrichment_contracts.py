"""Prompt Enrichment runtime contracts shared by the V1 service and the V2 workflow.

Request, state, result and error types plus two pure lineage/status helpers. Keeping them
here lets ``prompt_enrichment_runtime_v2`` depend on the contracts without importing the
V1 service module, so the V1 service can import the V2 workflow at module level instead of
inside every delegating method. ``prompt_enrichment_runtime`` re-exports every name for
existing importers.
"""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from jewelai_domain.clarification_state import (
    CauseState,
    Sha256,
)
from jewelai_domain.models import ImmutableModel
from jewelai_parser import (
    AnyFullMessageParseResult,
    AnyParserProposal,
)
from jewelai_prompts import CanonicalFinalPromptAssemblyV2_1 as FinalPromptAssembly
from jewelai_prompts import (
    FinalPromptDecisionLineage,
    FinalPromptReadiness,
    KnowledgeReleaseReference,
)
from jewelai_prompts.final_prompt_v3 import CanonicalFinalPromptAssemblyV3

from .clarification import (
    ClarificationImportance,
    ClarificationPlan,
)
from .clarification_answers import ClarificationDecision
from .clarification_v2 import (
    ClarificationAnswerRequestV2,
    ClarificationPlanV2,
    CorrectionRequestV2,
)
from .parsed_enrichment import (
    ParsedCandidateEnrichmentResult,
    ParsedCandidateEnrichmentResultV2,
)
from .preparation_contracts import (
    GenerationPreparationRequest,
    GenerationPreparationRequestV2,
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
    parse_result: AnyFullMessageParseResult
    parser_proposal: AnyParserProposal
    enrichment: ParsedCandidateEnrichmentResult
    workflow: PromptEnrichmentWorkflowState


class InitialEnrichmentRequestV2(InitialEnrichmentRequest):
    schema_version: Literal["2.0.0"]


class PersistedClarificationAnswerRequestV2(ClarificationAnswerRequestV2):
    session_id: UUID


class PersistedUserCorrectionRequestV2(CorrectionRequestV2):
    session_id: UUID


class PromptEnrichmentWorkflowStateV2(PromptEnrichmentWorkflowState):
    schema_version: Literal["2.0.0"]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    current_plan_version: Literal["2.0.0"]
    clarification_plan: ClarificationPlanV2
    final_output: CanonicalFinalPromptAssemblyV3
    preparation_expectations: GenerationPreparationRequestV2 | None
    availability_overlay_hash: Sha256
    effective_unresolved_frontier_hash: Sha256
    current_unresolved_causal_summaries: tuple[CauseState, ...]


class InitialEnrichmentRuntimeResultV2(InitialEnrichmentRuntimeResult):
    enrichment: ParsedCandidateEnrichmentResultV2
    workflow: PromptEnrichmentWorkflowStateV2


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
