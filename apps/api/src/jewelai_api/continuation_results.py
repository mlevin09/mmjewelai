"""Approved exact Correction3 evidence; native result readers remain frozen."""

import hashlib
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.clarification_state import Sha256, StrictEvidenceModel, TargetRef
from jewelai_domain.continuation import ContinuationContext, ContinuationFrame
from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import AnyDesignRevision
from jewelai_domain.preservation import contract_hash
from jewelai_domain.preservation_release import KeepReleaseDecision, KeepReleaseIntent
from jewelai_domain.questions import QuestionId
from jewelai_domain.questions_v2 import QuestionIdV2
from jewelai_parser import AnyParserProposal
from jewelai_parser.full_message_v1_2 import FullMessageParseResultV1_2
from jewelai_prompts.continuation import ContinuationEnrichmentResult
from pydantic import Field, model_validator

from .clarification import ClarificationEvidence, ClarificationOption
from .clarification_answers import (
    ClarificationAnswerOutcome,
    ClarificationAnswerReason,
    ClarificationDecision,
)
from .clarification_f05 import (
    ContinuationCorrectionRequest,
    KeepReleaseAnswerRequest,
    NativeAnswerRequest,
)
from .clarification_v2 import AcceptedTargetEvidence, ClarificationOptionV2, ResolutionAssertion
from .continuation_evaluation import ParsedEvaluationV3
from .correction_enrichment import CorrectionReason


class ContinuationCorrectionOutcome(StrEnum):
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    AWAITING_KEEP_RELEASE = "AWAITING_KEEP_RELEASE"


class ContinuationCorrectionResult(StrictEvidenceModel):
    correction_version: Literal["3.0.0"]
    context: ContinuationContext
    request: ContinuationCorrectionRequest
    request_id: UUID
    request_hash: Sha256
    session_id: UUID
    source: MessageSource
    source_message_sha256: Sha256
    source_parse: FullMessageParseResultV1_2
    native_proposal: AnyParserProposal
    correction_evaluation: ParsedEvaluationV3
    post_transition_evaluation: ParsedEvaluationV3
    previous_head: ContinuationFrame
    previous_revision_id: UUID
    new_revision_id: UUID | None
    authoritative_revision: AnyDesignRevision
    previous_enrichment_cycle_id: UUID
    next_enrichment_cycle_id: UUID
    next_enrichment_cycle_number: int
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    dictionary_artifact_version: str
    prompt_template_artifact_version: str
    semantic_hash: Sha256
    outcome: ContinuationCorrectionOutcome
    reason: (
        CorrectionReason | Literal["keep_release_required", "multiple_delta_release_unsupported"]
    )
    keep_intents: tuple[KeepReleaseIntent, ...]
    accepted_target_evidence: tuple[AcceptedTargetEvidence, ...]
    resolution_assertions: tuple[ResolutionAssertion, ...]
    next_enrichment_result: ContinuationEnrichmentResult
    content_hash: Sha256

    @property
    def scope(self):
        return self.context.scope

    @property
    def correction_text(self):
        return self.source_parse.original_text

    @property
    def parsed_correction(self):
        return self.source_parse

    @model_validator(mode="after")
    def validate_evidence(self):
        pin = self.context.release_pin
        request = self.request
        applied = self.outcome == "APPLIED"
        pending = self.outcome == "AWAITING_KEEP_RELEASE"
        if (
            self.request_id != request.request_id
            or self.session_id != self.context.scope.session_id
            or self.previous_head != request.expected_head
            or self.previous_revision_id != self.previous_head.revision_id
            or self.previous_enrichment_cycle_id != self.previous_head.enrichment_cycle_id
            or str(request.message_id) != self.source.message_id
            or self.source_parse != self.correction_evaluation.parse_result
            or self.source_parse != self.post_transition_evaluation.parse_result
            or self.native_proposal != self.correction_evaluation.parser_proposal
            or self.native_proposal.source != self.source
            or self.native_proposal.expected_revision_id != self.previous_revision_id
            or self.correction_evaluation.context != self.context
            or self.post_transition_evaluation.context != self.context
            or self.next_enrichment_result.context != self.context
            or self.next_enrichment_result.native
            != self.post_transition_evaluation.enrichment_result
            or self.next_enrichment_result.design_revision_id
            != str(self.authoritative_revision.revision_id)
            or self.next_enrichment_cycle_number != self.previous_head.enrichment_cycle_number + 1
            or applied != (self.new_revision_id is not None)
            or pending != bool(self.keep_intents)
            or pending
            and (len(self.keep_intents) != 1 or self.reason != "keep_release_required")
            or self.authoritative_revision.revision_id
            != (self.new_revision_id or self.previous_revision_id)
            or applied
            and self.authoritative_revision.parent_revision_id != self.previous_revision_id
            or self.post_transition_evaluation.parser_proposal.expected_revision_id
            != self.authoritative_revision.revision_id
            or (
                self.knowledge_package_id,
                self.knowledge_artifact_version,
                self.knowledge_runtime_sha256,
                self.knowledge_validation_report_sha256,
            )
            != (
                pin.package_id,
                pin.artifact_version,
                pin.runtime_sha256,
                pin.validation_report_sha256,
            )
            or self.dictionary_artifact_version
            != self.context.artifact_pins.dictionary_artifact_version
            or self.prompt_template_artifact_version
            != self.context.artifact_pins.prompt_template_artifact_version
        ):
            raise ValueError("Correction3 request/source/context/canonical evidence mismatch")
        if self.source_message_sha256 != hashlib.sha256(
            self.source_parse.original_text.encode("utf-8")
        ).hexdigest() or self.request_hash != contract_hash(
            "jewelai.CorrectionRequest/3.0.0",
            dict(
                scope=self.context.scope,
                retained_base=self.context.retained_base,
                request=request,
                source_message_sha256=self.source_message_sha256,
            ),
        ):
            raise ValueError("Correction3 source/request commitment mismatch")
        if self.context.retained_base == "L" and (
            self.accepted_target_evidence or self.resolution_assertions
        ):
            raise ValueError("L cannot acquire F accepted-target assertions")
        if self.outcome not in {"APPLIED", "NO_CHANGE"} and (
            self.accepted_target_evidence or self.resolution_assertions
        ):
            raise ValueError("Non-applying correction cannot resolve native causes")
        for intent in self.keep_intents:
            if (
                intent.context != self.context
                or intent.origin_head != self.previous_head
                or intent.source != self.source
                or intent.message_sha256 != self.source_message_sha256
            ):
                raise ValueError("Correction3 intent does not originate in its actual request")
        for assertion in self.resolution_assertions:
            index = assertion.accepted_target_evidence_index
            if (
                index is None
                or index >= len(self.accepted_target_evidence)
                or self.accepted_target_evidence[index].target != assertion.target
            ):
                raise ValueError("Correction3 assertion has no exact accepted canonical target")
        if self.semantic_hash != correction_semantic_hash(self):
            raise ValueError("Correction3 semantic integrity mismatch")
        if self.content_hash != contract_hash(
            "jewelai.CorrectionResult/3.0.0", self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("Correction3 integrity mismatch")
        return self


def correction_semantic_hash(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return contract_hash(
        "jewelai.CorrectionSemantic/3.0.0",
        {
            key: value[key]
            for key in (
                "request_hash",
                "source_message_sha256",
                "source_parse",
                "native_proposal",
                "outcome",
                "reason",
                "previous_head",
                "keep_intents",
            )
        },
    )


class NativeLDecisionEvidence(StrictEvidenceModel):
    retained_base: Literal["L"]
    semantic_question_id: QuestionId
    target: str
    subject: str | None
    selected_option: ClarificationOption | None
    source_candidate_ids: tuple[str, ...]
    source_proposal_ids: tuple[str, ...]
    evidence: tuple[ClarificationEvidence, ...]
    question_resolved: bool
    blocks_progression: bool
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    question_artifact_version: str
    rules_artifact_version: str


class NativeFDecisionEvidence(NativeLDecisionEvidence):
    retained_base: Literal["F"]
    semantic_question_id: QuestionIdV2
    target: TargetRef
    selected_option: ClarificationOptionV2 | None
    selected_option_id: str | None


class _AnswerResultV3(StrictEvidenceModel):
    answer_version: Literal["3.0.0"]
    context: ContinuationContext
    answer_id: UUID
    request_hash: Sha256
    session_id: UUID
    source: MessageSource
    message_sha256: Sha256
    previous_head: ContinuationFrame
    clarification_plan_id: UUID
    clarification_id: str
    plan_content_hash: Sha256
    decision: ClarificationDecision
    outcome: ClarificationAnswerOutcome
    reason: ClarificationAnswerReason | Literal["keep_release_authorized", "keep_release_rejected"]
    previous_revision_id: UUID
    new_revision_id: UUID | None
    resulting_revision: AnyDesignRevision | None
    answer_hash: Sha256
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    question_artifact_version: str
    rules_artifact_version: str
    accepted_target_evidence: tuple[AcceptedTargetEvidence, ...]
    resolution_assertions: tuple[ResolutionAssertion, ...]
    next_enrichment_result: ContinuationEnrichmentResult
    content_hash: Sha256

    @property
    def scope(self):
        return self.context.scope

    @model_validator(mode="after")
    def validate_answer_bindings(self):
        request, pin = self.request, self.context.release_pin
        if (
            self.answer_id != request.answer_id
            or self.answer_hash != self.request_hash
            or self.session_id != self.context.scope.session_id
            or self.previous_head != request.expected_head
            or self.previous_revision_id != self.previous_head.revision_id
            or self.clarification_plan_id
            != request.clarification_plan_id
            != self.previous_head.plan_id
            or self.clarification_plan_id != self.previous_head.plan_id
            or self.clarification_id != request.clarification_id
            or self.plan_content_hash != self.previous_head.plan_hash
            or self.source.message_id != str(request.message_id)
            or (self.new_revision_id is None) != (self.resulting_revision is None)
            or (self.outcome == "APPLIED") != (self.new_revision_id is not None)
            or self.resulting_revision is not None
            and (
                self.resulting_revision.revision_id != self.new_revision_id
                or self.resulting_revision.parent_revision_id != self.previous_revision_id
            )
            or self.next_enrichment_result.context != self.context
            or self.next_enrichment_result.design_revision_id
            != str(self.new_revision_id or self.previous_revision_id)
            or (
                self.knowledge_package_id,
                self.knowledge_artifact_version,
                self.knowledge_runtime_sha256,
                self.knowledge_validation_report_sha256,
            )
            != (
                pin.package_id,
                pin.artifact_version,
                pin.runtime_sha256,
                pin.validation_report_sha256,
            )
            or (self.question_artifact_version, self.rules_artifact_version)
            != (
                self.context.artifact_pins.question_artifact_version,
                self.context.artifact_pins.rules_artifact_version,
            )
        ):
            raise ValueError("Answer3 source/request/canonical bindings mismatch")
        if self.request_hash != contract_hash(
            "jewelai.AnswerRequest/3.0.0",
            dict(
                scope=self.context.scope,
                retained_base=self.context.retained_base,
                request=request,
                source_message_sha256=self.message_sha256,
            ),
        ):
            raise ValueError("Answer3 request commitment mismatch")
        if self.context.retained_base == "L" and (
            self.accepted_target_evidence or self.resolution_assertions
        ):
            raise ValueError("L cannot acquire F resolution assertions")
        for assertion in self.resolution_assertions:
            index = assertion.accepted_target_evidence_index
            if index is not None and (
                index >= len(self.accepted_target_evidence)
                or self.accepted_target_evidence[index].target != assertion.target
            ):
                raise ValueError("Answer3 assertion lacks its accepted canonical target")
        if self.content_hash != contract_hash(
            "jewelai.AnswerResult/3.0.0", self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("Answer3 integrity mismatch")
        return self


class KeepAnswerResultV3(_AnswerResultV3):
    answer_kind: Literal["KEEP_RELEASE"]
    request: KeepReleaseAnswerRequest
    keep_decision: KeepReleaseDecision

    @model_validator(mode="after")
    def validate_release(self):
        d = self.keep_decision
        if (
            d.decision_id != self.answer_id
            or d.request_hash != self.request_hash
            or d.context != self.context
            or d.previous_head != self.previous_head
            or d.source != self.source
            or d.message_sha256 != self.message_sha256
            or d.intent_id != self.request.intent_id
            or d.decision != self.request.decision
            or self.decision != d.decision
            or self.outcome != d.outcome
            or self.new_revision_id != d.resulting_revision_id
        ):
            raise ValueError("Answer3 is not its exact typed KEEP decision")
        return self


class NativeAnswerResultV3(_AnswerResultV3):
    answer_kind: Literal["NATIVE"]
    request: NativeAnswerRequest
    native_result: Annotated[
        NativeLDecisionEvidence | NativeFDecisionEvidence, Field(discriminator="retained_base")
    ]

    @model_validator(mode="after")
    def validate_native(self):
        p = self.native_result
        if (
            p.retained_base != self.context.retained_base
            or self.request.native.retained_base != p.retained_base
            or self.decision != self.request.native.decision
        ):
            raise ValueError("Answer3 native profile/decision mismatch")
        if (
            p.knowledge_package_id,
            p.knowledge_artifact_version,
            p.knowledge_runtime_sha256,
            p.knowledge_validation_report_sha256,
            p.question_artifact_version,
            p.rules_artifact_version,
        ) != (
            self.knowledge_package_id,
            self.knowledge_artifact_version,
            self.knowledge_runtime_sha256,
            self.knowledge_validation_report_sha256,
            self.question_artifact_version,
            self.rules_artifact_version,
        ):
            raise ValueError("Answer3 native artifact mismatch")
        return self


ContinuationAnswerResult = Annotated[
    KeepAnswerResultV3 | NativeAnswerResultV3, Field(discriminator="answer_kind")
]
