"""Deterministic internal user-correction and re-enrichment orchestration.

This boundary is intentionally not routed or persisted. It validates one correction against the
authoritative session/revision and append-only enrichment lineage, applies only an existing Parser
Proposal through the domain EDIT transition, and prepares the next verified enrichment result for
later transactional persistence.
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from jewelai_domain.dictionary import DictionaryRegistry
from jewelai_domain.knowledge_activation import (
    ActiveKnowledgeRuntime,
    ProductionValidationReport,
    Sha256,
)
from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)
from jewelai_domain.models import DesignRevision, ImmutableModel, MessageSource, Text
from jewelai_domain.revisions import RevisionConflict, revise_design
from jewelai_parser import FullMessageParseResult, parse_full_message
from jewelai_persistence import (
    EnrichmentCycleRecord,
    KnowledgeReleasePinConflictError,
)
from jewelai_prompts import PromptEnrichmentResult, PromptTemplateBundle
from pydantic import Field, model_validator

from .clarification_answers import ClarificationAnswerResult
from .parsed_enrichment import (
    CandidateDispositionOutcome,
    CandidateDispositionReason,
    ParsedCandidateEnrichmentResult,
    enrich_parsed_candidates_with_active_release,
)

CORRECTION_REENRICHMENT_VERSION = "1.0.0"


class CorrectionOutcome(StrEnum):
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class CorrectionReason(StrEnum):
    SUPPORTED_CHANGES_APPLIED = "supported_changes_applied"
    VALUE_ALREADY_CURRENT = "value_already_current"
    PRESERVATION_RETAINED = "preservation_retained"
    CONSTRAINT_RETAINED = "constraint_retained"
    PREFERENCE_REQUIRES_ACCEPTANCE = "preference_requires_acceptance"
    AMBIGUOUS_OR_UNRESOLVED = "ambiguous_or_unresolved"
    UNSUPPORTED_TARGET = "unsupported_target"
    PARSER_REJECTED = "parser_rejected"
    REVISION_TRANSITION_DEFERRED = "revision_transition_deferred"
    NO_SUPPORTED_CANDIDATE = "no_supported_candidate"


class CorrectionErrorCode(StrEnum):
    CROSS_SESSION = "cross_session"
    STALE_REVISION = "stale_revision"
    PREVIOUS_CYCLE_MISMATCH = "previous_cycle_mismatch"
    DECISION_LINEAGE_MISMATCH = "decision_lineage_mismatch"
    RELEASE_MISMATCH = "release_mismatch"
    ARTIFACT_MISMATCH = "artifact_mismatch"


class CorrectionInputError(ValueError):
    """Typed fail-closed error for correction lineage and artifact validation."""

    def __init__(self, code: CorrectionErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class UserCorrection(ImmutableModel):
    session_id: UUID
    expected_revision_id: UUID
    correction_text: Text
    locale: Literal["en", "ru"]
    source: MessageSource
    previous_enrichment_cycle_id: UUID
    previous_enrichment_cycle_number: int = Field(ge=1)
    previous_enrichment_content_hash: Sha256
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    dictionary_artifact_version: str
    prompt_template_artifact_version: str


class CorrectionReenrichmentResult(ImmutableModel):
    correction_version: Literal["1.0.0"] = CORRECTION_REENRICHMENT_VERSION
    session_id: UUID
    correction_text: Text
    locale: Literal["en", "ru"]
    source: MessageSource
    previous_revision_id: UUID
    new_revision_id: UUID | None = None
    authoritative_revision: DesignRevision
    previous_enrichment_cycle_id: UUID
    previous_enrichment_cycle_number: int
    previous_enrichment_content_hash: Sha256
    next_enrichment_cycle_number: int
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    dictionary_artifact_version: str
    prompt_template_artifact_version: str
    prior_answer_results: tuple[ClarificationAnswerResult, ...]
    parsed_correction: FullMessageParseResult
    correction_evaluation: ParsedCandidateEnrichmentResult
    post_transition_evaluation: ParsedCandidateEnrichmentResult
    next_enrichment_result: PromptEnrichmentResult
    outcome: CorrectionOutcome
    reason: CorrectionReason
    semantic_hash: Sha256
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_lineage_and_hashes(self):
        if self.parsed_correction.original_text != self.correction_text:
            raise ValueError("correction parse does not preserve the exact original text")
        if self.correction_evaluation.parse_result != self.parsed_correction:
            raise ValueError("correction evaluation parse lineage mismatch")
        if (
            self.correction_evaluation.parser_proposal.expected_revision_id
            != self.previous_revision_id
        ):
            raise ValueError("correction evaluation revision lineage mismatch")
        expected_authoritative_id = self.new_revision_id or self.previous_revision_id
        if self.authoritative_revision.revision_id != expected_authoritative_id:
            raise ValueError("authoritative correction revision identity mismatch")
        if self.new_revision_id is not None:
            if self.authoritative_revision.parent_revision_id != self.previous_revision_id:
                raise ValueError("corrected Product State parent lineage mismatch")
        elif self.outcome == CorrectionOutcome.APPLIED:
            raise ValueError("an applied correction requires a new Product State revision")
        if (
            self.post_transition_evaluation.parse_result != self.parsed_correction
            or self.post_transition_evaluation.parser_proposal.expected_revision_id
            != expected_authoritative_id
            or self.next_enrichment_result != self.post_transition_evaluation.enrichment_result
        ):
            raise ValueError("post-transition enrichment lineage mismatch")
        if self.next_enrichment_cycle_number != self.previous_enrichment_cycle_number + 1:
            raise ValueError("next enrichment cycle number is not append-only")
        if self.semantic_hash != _hash(_semantic_payload(self)):
            raise ValueError("correction semantic hash mismatch")
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if self.content_hash != _hash(payload):
            raise ValueError("correction result content hash mismatch")
        return self


def process_user_correction(
    correction: UserCorrection,
    *,
    authoritative_session_id: UUID,
    current_revision: DesignRevision,
    previous_cycle: EnrichmentCycleRecord,
    prior_answer_results: tuple[ClarificationAnswerResult, ...],
    dictionary: DictionaryRegistry,
    templates: PromptTemplateBundle,
    artifact_store: KnowledgeArtifactStore,
    active_release: ActiveKnowledgeRuntime | object,
    validation_report: ProductionValidationReport | object,
    created_at: datetime,
    template_id: str = "jewelry_visualization",
) -> CorrectionReenrichmentResult:
    """Apply one safe correction and prepare the next immutable enrichment-cycle payload."""

    request = UserCorrection.model_validate(correction)
    revision = DesignRevision.model_validate(current_revision)
    templates = PromptTemplateBundle.model_validate(templates)
    answers = tuple(ClarificationAnswerResult.model_validate(item) for item in prior_answer_results)

    if request.session_id != authoritative_session_id:
        raise CorrectionInputError(
            CorrectionErrorCode.CROSS_SESSION,
            "correction does not belong to the authoritative session",
        )
    if request.expected_revision_id != revision.revision_id:
        raise CorrectionInputError(
            CorrectionErrorCode.STALE_REVISION,
            "correction references a stale Product State revision",
        )
    _validate_artifacts(request, dictionary, templates)
    _validate_previous_cycle(request, previous_cycle)
    _validate_answer_lineage(request, previous_cycle, answers, revision)
    verified = _load_pinned_release(
        request,
        previous_cycle,
        artifact_store,
        active_release=active_release,
        validation_report=validation_report,
    )

    parsed = parse_full_message(
        request.correction_text,
        locale=request.locale,
        dictionary=dictionary,
        knowledge_runtime=verified.compiled_runtime,
    )
    evaluation = _evaluate(
        revision,
        parsed,
        request,
        dictionary=dictionary,
        templates=templates,
        artifact_store=artifact_store,
        active_release=verified,
        validation_report=validation_report,
        template_id=template_id,
    )
    authoritative = revision
    new_revision = None
    if evaluation.parser_proposal.has_changes:
        try:
            authoritative = revise_design(
                revision,
                evaluation.parser_proposal.proposed_design,
                expected_revision_id=revision.revision_id,
                source=request.source,
                reason="Applied an explicitly sourced user correction",
                created_at=created_at,
            )
            new_revision = authoritative
            outcome = CorrectionOutcome.APPLIED
            reason = CorrectionReason.SUPPORTED_CHANGES_APPLIED
        except RevisionConflict:
            outcome = CorrectionOutcome.DEFERRED
            reason = CorrectionReason.REVISION_TRANSITION_DEFERRED
    else:
        outcome, reason = _nonmutating_outcome(evaluation)

    post_transition = (
        _evaluate(
            authoritative,
            parsed,
            request,
            dictionary=dictionary,
            templates=templates,
            artifact_store=artifact_store,
            active_release=verified,
            validation_report=validation_report,
            template_id=template_id,
        )
        if new_revision is not None
        else evaluation
    )
    payload = {
        "correction_version": CORRECTION_REENRICHMENT_VERSION,
        "session_id": request.session_id,
        "correction_text": request.correction_text,
        "locale": request.locale,
        "source": request.source,
        "previous_revision_id": revision.revision_id,
        "new_revision_id": new_revision.revision_id if new_revision is not None else None,
        "authoritative_revision": authoritative,
        "previous_enrichment_cycle_id": previous_cycle.enrichment_cycle_id,
        "previous_enrichment_cycle_number": previous_cycle.cycle_number,
        "previous_enrichment_content_hash": previous_cycle.result.content_hash,
        "next_enrichment_cycle_number": previous_cycle.cycle_number + 1,
        "knowledge_package_id": request.knowledge_package_id,
        "knowledge_artifact_version": request.knowledge_artifact_version,
        "knowledge_runtime_sha256": request.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": request.knowledge_validation_report_sha256,
        "dictionary_artifact_version": dictionary.artifact_version,
        "prompt_template_artifact_version": str(templates.artifact_version),
        "prior_answer_results": answers,
        "parsed_correction": parsed,
        "correction_evaluation": evaluation,
        "post_transition_evaluation": post_transition,
        "next_enrichment_result": post_transition.enrichment_result,
        "outcome": outcome,
        "reason": reason,
    }
    semantic_hash = _hash(_semantic_payload(payload))
    content_payload = _json({**payload, "semantic_hash": semantic_hash})
    return CorrectionReenrichmentResult(
        **payload,
        semantic_hash=semantic_hash,
        content_hash=_hash(content_payload),
    )


def _evaluate(
    revision,
    parsed,
    request,
    *,
    dictionary,
    templates,
    artifact_store,
    active_release,
    validation_report,
    template_id,
):
    return enrich_parsed_candidates_with_active_release(
        revision,
        parse_result=parsed,
        source=request.source,
        dictionary=dictionary,
        templates=templates,
        artifact_store=artifact_store,
        knowledge_package_id=request.knowledge_package_id,
        knowledge_artifact_version=request.knowledge_artifact_version,
        active_release=active_release,
        validation_report=validation_report,
        template_id=template_id,
    )


def _validate_artifacts(request, dictionary, templates):
    if (
        request.dictionary_artifact_version != dictionary.artifact_version
        or request.prompt_template_artifact_version != str(templates.artifact_version)
    ):
        raise CorrectionInputError(
            CorrectionErrorCode.ARTIFACT_MISMATCH,
            "correction artifacts do not match the explicitly supplied versions",
        )


def _validate_previous_cycle(request, cycle):
    if (
        cycle.session_id != request.session_id
        or cycle.enrichment_cycle_id != request.previous_enrichment_cycle_id
        or cycle.cycle_number != request.previous_enrichment_cycle_number
        or cycle.result.content_hash != request.previous_enrichment_content_hash
    ):
        raise CorrectionInputError(
            CorrectionErrorCode.PREVIOUS_CYCLE_MISMATCH,
            "correction does not match the previous append-only enrichment cycle",
        )
    try:
        result = PromptEnrichmentResult.model_validate(cycle.result)
    except ValueError as exc:
        raise CorrectionInputError(
            CorrectionErrorCode.PREVIOUS_CYCLE_MISMATCH,
            "previous enrichment cycle failed integrity validation",
        ) from exc
    if result.compiled_prompt.template_artifact_version != request.prompt_template_artifact_version:
        raise CorrectionInputError(
            CorrectionErrorCode.ARTIFACT_MISMATCH,
            "previous enrichment cycle used a different Prompt Template artifact",
        )


def _validate_answer_lineage(request, cycle, answers, revision):
    cursor = cycle.specification_revision_id
    last_snapshot = None
    release_identity = _request_release_identity(request)
    for answer in answers:
        if answer.session_id != request.session_id:
            raise CorrectionInputError(
                CorrectionErrorCode.CROSS_SESSION,
                "prior clarification answer belongs to a different session",
            )
        if (
            answer.previous_revision_id != cursor
            or _answer_release_identity(answer) != release_identity
        ):
            raise CorrectionInputError(
                CorrectionErrorCode.DECISION_LINEAGE_MISMATCH,
                "prior clarification answer lineage does not continue the enrichment cycle",
            )
        if answer.new_revision_id is not None:
            cursor = answer.new_revision_id
            last_snapshot = answer.resulting_revision
    if cursor != revision.revision_id or (last_snapshot is not None and last_snapshot != revision):
        raise CorrectionInputError(
            CorrectionErrorCode.DECISION_LINEAGE_MISMATCH,
            "prior clarification decisions do not reach the current Product State revision",
        )


def _load_pinned_release(
    request,
    cycle,
    artifact_store,
    *,
    active_release,
    validation_report,
):
    expected = _request_release_identity(request)
    cycle_identity = (
        cycle.release_pin.package_id,
        cycle.release_pin.artifact_version,
        cycle.release_pin.runtime_sha256,
        cycle.release_pin.validation_report_sha256,
    )
    if cycle_identity != expected:
        raise CorrectionInputError(
            CorrectionErrorCode.RELEASE_MISMATCH,
            "correction release does not match the pinned enrichment cycle",
        )
    try:
        verified = cycle.release_pin.restore_verified_runtime(
            artifact_store,
            active_release=active_release,
            validation_report=validation_report,
        )
    except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError) as exc:
        raise CorrectionInputError(
            CorrectionErrorCode.RELEASE_MISMATCH,
            "correction Knowledge release failed ACTIVE verification",
        ) from exc
    return verified


def _nonmutating_outcome(evaluation):
    if evaluation.parser_proposal.issues:
        return CorrectionOutcome.REJECTED, CorrectionReason.PARSER_REJECTED
    reasons = {item.reason for item in evaluation.dispositions}
    if not reasons:
        return CorrectionOutcome.DEFERRED, CorrectionReason.NO_SUPPORTED_CANDIDATE
    no_change_reasons = {
        CandidateDispositionReason.ALREADY_CURRENT,
        CandidateDispositionReason.PRESERVATION_RETAINED,
    }
    unresolved_fillers = all(
        item.reason in no_change_reasons
        or (
            item.reason == CandidateDispositionReason.UNRESOLVED_CANDIDATE
            and item.candidate.target is None
        )
        for item in evaluation.dispositions
    )
    if reasons & no_change_reasons and unresolved_fillers:
        reason = (
            CorrectionReason.PRESERVATION_RETAINED
            if CandidateDispositionReason.PRESERVATION_RETAINED in reasons
            else CorrectionReason.VALUE_ALREADY_CURRENT
        )
        return CorrectionOutcome.NO_CHANGE, reason
    if CandidateDispositionReason.PROHIBITION_RETAINED in reasons:
        return CorrectionOutcome.DEFERRED, CorrectionReason.CONSTRAINT_RETAINED
    if CandidateDispositionReason.PREFERENCE_REQUIRES_ACCEPTANCE in reasons:
        return CorrectionOutcome.DEFERRED, CorrectionReason.PREFERENCE_REQUIRES_ACCEPTANCE
    if reasons & {
        CandidateDispositionReason.AMBIGUOUS_CANDIDATE,
        CandidateDispositionReason.UNRESOLVED_CANDIDATE,
        CandidateDispositionReason.DUPLICATE_TARGET_CANDIDATES,
    }:
        return CorrectionOutcome.DEFERRED, CorrectionReason.AMBIGUOUS_OR_UNRESOLVED
    if any(
        item.outcome == CandidateDispositionOutcome.DEFERRED for item in evaluation.dispositions
    ):
        return CorrectionOutcome.DEFERRED, CorrectionReason.UNSUPPORTED_TARGET
    return CorrectionOutcome.DEFERRED, CorrectionReason.NO_SUPPORTED_CANDIDATE


def _request_release_identity(request):
    return (
        request.knowledge_package_id,
        request.knowledge_artifact_version,
        request.knowledge_runtime_sha256,
        request.knowledge_validation_report_sha256,
    )


def _answer_release_identity(answer):
    return (
        answer.knowledge_package_id,
        answer.knowledge_artifact_version,
        answer.knowledge_runtime_sha256,
        answer.knowledge_validation_report_sha256,
    )


def _semantic_payload(value):
    if isinstance(value, CorrectionReenrichmentResult):
        fields = {
            "correction_version": value.correction_version,
            "correction_text": value.correction_text,
            "locale": value.locale,
            "knowledge_package_id": value.knowledge_package_id,
            "knowledge_artifact_version": value.knowledge_artifact_version,
            "knowledge_runtime_sha256": value.knowledge_runtime_sha256,
            "knowledge_validation_report_sha256": value.knowledge_validation_report_sha256,
            "dictionary_artifact_version": value.dictionary_artifact_version,
            "prompt_template_artifact_version": value.prompt_template_artifact_version,
            "parsed_correction": value.parsed_correction,
            "correction_evaluation": value.correction_evaluation,
            "post_transition_evaluation": value.post_transition_evaluation,
            "authoritative_revision": value.authoritative_revision,
            "outcome": value.outcome,
            "reason": value.reason,
        }
    else:
        fields = value
    parsed = fields["parsed_correction"]
    correction_evaluation = fields["correction_evaluation"]
    post_transition = fields["post_transition_evaluation"]
    authoritative = fields["authoritative_revision"]
    return _json(
        {
            "correction_version": fields["correction_version"],
            "correction_text": fields["correction_text"],
            "locale": fields["locale"],
            "knowledge_package_id": fields["knowledge_package_id"],
            "knowledge_artifact_version": fields["knowledge_artifact_version"],
            "knowledge_runtime_sha256": fields["knowledge_runtime_sha256"],
            "knowledge_validation_report_sha256": fields["knowledge_validation_report_sha256"],
            "dictionary_artifact_version": fields["dictionary_artifact_version"],
            "prompt_template_artifact_version": fields["prompt_template_artifact_version"],
            "parsed_candidates": parsed.candidates,
            "correction_dispositions": correction_evaluation.dispositions,
            "resulting_design": authoritative.design,
            "post_transition_dispositions": post_transition.dispositions,
            "outcome": fields["outcome"],
            "reason": fields["reason"],
        }
    )


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _hash(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
