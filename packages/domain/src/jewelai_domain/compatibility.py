"""F05 immutable compatibility evidence; derivation/authorization belongs to runtime."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from .clarification_state import EvidenceScope, Sha256, StrictEvidenceModel, TargetRef
from .continuation import ContinuationArtifactPins, ContinuationFrame, ContinuationFrameCore
from .preservation import contract_hash


class CompatibilityRecordRef(StrictEvidenceModel):
    id: UUID
    hash: Sha256


class AcceptedCompatibilityEvent(StrictEvidenceModel):
    kind: Literal["correction", "keep_release_answer"]
    record_id: UUID
    content_hash: Sha256


class CausalCorrectionProof(StrictEvidenceModel):
    kind: Literal["accepted_target_replaces_unknown"]
    original_answer_ref: CompatibilityRecordRef
    original_plan_ref: CompatibilityRecordRef
    target: TargetRef
    accepted_event_ref: AcceptedCompatibilityEvent
    source_message_id: UUID
    source_parse_hash: Sha256
    before_revision_ref: CompatibilityRecordRef
    after_revision_ref: CompatibilityRecordRef
    current_state_sha256: Sha256
    ancestry_refs: tuple[CompatibilityRecordRef, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.CausalCorrectionProof/1.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Causal compatibility proof integrity mismatch")
        return self


class CompatibilitySourceSpan(StrictEvidenceModel):
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, gt=0)
    text_sha256: Sha256

    @model_validator(mode="after")
    def validate_order(self):
        if self.end <= self.start:
            raise ValueError("Compatibility source span is invalid")
        return self


class ContextConsumedProof(StrictEvidenceModel):
    kind: Literal["context_owner_token_consumed"]
    original_correction_ref: CompatibilityRecordRef
    original_parse_hash: Sha256
    residual_candidate_id: str
    residual_span: CompatibilitySourceSpan
    accepted_candidate_ids: tuple[str, ...]
    accepted_target: TargetRef
    accepted_value_sha256: Sha256
    source_message_id: UUID
    context_classifier_version: Literal["1.0.0"]
    current_state_sha256: Sha256
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.ContextConsumedProof/1.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Context compatibility proof integrity mismatch")
        return self


CompatibilityProof = Annotated[
    CausalCorrectionProof | ContextConsumedProof, Field(discriminator="kind")
]


class CompatibilityBlockerRef(StrictEvidenceModel):
    kind: Literal["clarification", "correction"]
    id: str
    hash: Sha256


class CompatibilityReadinessProjection(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    projection_id: Literal["jewelai.legacy-l.compat/1.0.0"]
    scope: EvidenceScope
    build_mode: Literal["embedded_plan", "read_only_output"]
    current_frame_core: ContinuationFrameCore
    evidence_head: ContinuationFrame
    retained_artifact_pins: ContinuationArtifactPins
    legacy_history_root_sha256: Sha256
    proofs: tuple[CompatibilityProof, ...]
    remaining_blocker_refs: tuple[CompatibilityBlockerRef, ...]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != contract_hash(
            "jewelai.CompatibilityReadinessProjection/1.0.0",
            self.model_dump(mode="json", exclude={"content_hash"}),
        ):
            raise ValueError("Legacy compatibility projection integrity mismatch")
        return self
