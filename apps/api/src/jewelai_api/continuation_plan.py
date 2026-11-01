"""F05 Plan3 stores native core evidence, never its own sealed frontier/hash."""

from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.clarification_state import (
    CanonicalAvailabilityOverlay,
    CauseDefinition,
    FrontierCore,
    Sha256,
    StrictEvidenceModel,
)
from jewelai_domain.compatibility import CompatibilityReadinessProjection
from jewelai_domain.continuation import (
    ContinuationContext,
    ContinuationFrame,
    ContinuationFrameCore,
    ContinuationRecordReference,
)
from jewelai_domain.preservation import ProtectionProjection, contract_hash
from jewelai_domain.rules import RuleDecision
from jewelai_domain.rules_v2 import RuleDecisionV2
from jewelai_prompts.final_prompt import FinalPromptConstraintEvidence, FinalPromptDecisionLineage
from pydantic import Field, model_validator

from .clarification import ClarificationQuestion, UnaskedClarificationEvidence
from .clarification_f05 import ContinuationAdmissionRequest, ContinuationResumeRequest
from .clarification_v2 import ClarificationQuestionV2
from .conflict_evidence import ConflictEvidence
from .continuation_preview import KeepOfferQuestion, NativePreviewQuestion


class NativeLPlanEvidence(StrictEvidenceModel):
    retained_base: Literal["L"]
    rule_decision: RuleDecision
    native_questions: tuple[ClarificationQuestion, ...]
    native_decision_audit: tuple[FinalPromptDecisionLineage, ...]


class NativeFPlanEvidence(StrictEvidenceModel):
    retained_base: Literal["F"]
    rule_decision: RuleDecisionV2
    native_questions: tuple[ClarificationQuestionV2, ...]
    conflicts: tuple[ConflictEvidence, ...]
    cause_definitions: tuple[CauseDefinition, ...]
    frontier_core: FrontierCore
    availability_overlay: CanonicalAvailabilityOverlay


class AdmissionTrigger(StrictEvidenceModel):
    trigger_kind: Literal["ADMISSION"]
    request: ContinuationAdmissionRequest
    request_hash: Sha256
    source_message_sha256: Sha256
    previous_head: ContinuationFrame
    legacy_interpreter_id: Literal["legacy-bc34-1.1"]
    new_interpreter_id: Literal["f05-1.2"]


class EventTrigger(StrictEvidenceModel):
    trigger_kind: Literal["CORRECTION", "ANSWER"]
    record_id: UUID
    result_hash: Sha256
    request_hash: Sha256
    message_id: UUID
    message_sha256: Sha256
    previous_head: ContinuationFrame


class ResumeTrigger(StrictEvidenceModel):
    trigger_kind: Literal["RESUME"]
    request: ContinuationResumeRequest
    request_hash: Sha256
    source_message_sha256: Sha256
    previous_head: ContinuationFrame


class ContinuationPlan(StrictEvidenceModel):
    plan_version: Literal["3.0.0"]
    context: ContinuationContext
    allocated_current_frame_core: ContinuationFrameCore
    previous_head: ContinuationFrame
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: Sha256
    knowledge_validation_report_sha256: Sha256
    dictionary_artifact_version: str
    question_artifact_version: str
    rules_artifact_version: str
    locale: Literal["en", "ru"]
    role_id: str
    native_base: Annotated[
        NativeLPlanEvidence | NativeFPlanEvidence, Field(discriminator="retained_base")
    ]
    historical_base_plan_ref: ContinuationRecordReference
    questions: tuple[
        Annotated[NativePreviewQuestion | KeepOfferQuestion, Field(discriminator="question_kind")],
        ...,
    ]
    unasked_evidence: tuple[UnaskedClarificationEvidence, ...]
    constraint_evidence: tuple[FinalPromptConstraintEvidence, ...]
    protection_projection: ProtectionProjection
    compatibility_projection: CompatibilityReadinessProjection | None
    trigger: Annotated[
        AdmissionTrigger | EventTrigger | ResumeTrigger, Field(discriminator="trigger_kind")
    ]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_plan(self):
        core, pins, pin = (
            self.allocated_current_frame_core,
            self.context.artifact_pins,
            self.context.release_pin,
        )
        if (
            str(core.revision_id) != self.design_revision_id
            or self.native_base.retained_base != self.context.retained_base
            or self.protection_projection.scope != self.context.scope
            or self.protection_projection.current_revision_id != core.revision_id
            or self.protection_projection.current_revision_sha256 != core.revision_sha256
            or self.trigger.previous_head != self.previous_head
            or (
                self.dictionary_artifact_version,
                self.question_artifact_version,
                self.rules_artifact_version,
            )
            != (
                pins.dictionary_artifact_version,
                pins.question_artifact_version,
                pins.rules_artifact_version,
            )
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
            or core.enrichment_cycle_number != self.previous_head.enrichment_cycle_number + 1
        ):
            raise ValueError("Continuation plan context/frame mismatch")
        if self.context.retained_base == "F":
            native = self.native_base
            if (
                native.frontier_core.scope != self.context.scope
                or native.frontier_core.current_revision_id != core.revision_id
                or native.frontier_core.revision_sha256 != core.revision_sha256
                or native.availability_overlay.canonical_revision_id != core.revision_id
            ):
                raise ValueError("Continuation F native core mismatch")
        if self.content_hash != contract_hash(
            "jewelai.ClarificationPlan/3.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Continuation plan integrity mismatch")
        return self
