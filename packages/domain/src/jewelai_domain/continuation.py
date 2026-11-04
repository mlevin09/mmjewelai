"""Approved F05 immutable continuation context and full-head CAS evidence."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .clarification_state import (
    ArtifactPins,
    EvidenceScope,
    ReleasePin,
    Sha256,
    StrictEvidenceModel,
)


class ContinuationFrame(StrictEvidenceModel):
    revision_id: UUID
    revision_sha256: Sha256
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int = Field(strict=True, ge=1)
    enrichment_result_hash: Sha256
    plan_id: UUID
    plan_hash: Sha256
    history_root_sha256: Sha256


class ContinuationFrameCore(StrictEvidenceModel):
    """Allocated current IDs; deliberately excludes its own plan/history hashes."""

    revision_id: UUID
    revision_sha256: Sha256
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int = Field(strict=True, ge=1)
    enrichment_result_hash: Sha256
    plan_id: UUID


class ContinuationArtifactPins(ArtifactPins):
    """Retained L/F pins in the NEW context; frozen F04 pins stay F-only."""

    question_schema_version: Literal["1.0.0", "2.0.0"]
    question_artifact_version: Literal["1.0.0", "2.0.0"]
    rules_schema_version: Literal["1.0.0", "2.0.0"]
    rules_artifact_version: Literal["1.0.0", "2.0.0"]

    @model_validator(mode="after")
    def validate_retained_versions(self):
        versions = (
            self.question_schema_version,
            self.question_artifact_version,
            self.rules_schema_version,
            self.rules_artifact_version,
        )
        if len(set(versions)) != 1:
            raise ValueError("Mixed retained native artifact profiles are not allowed")
        return self


class ContinuationContext(StrictEvidenceModel):
    scope: EvidenceScope
    retained_base: Literal["L", "F"]
    extension_profile: Literal["jewelai.prompt-enrichment.f05/1.0.0"]
    release_pin: ReleasePin
    artifact_pins: ContinuationArtifactPins
    parser_interpreter_id: Literal["legacy-bc34-1.1", "f05-1.2"]

    @model_validator(mode="after")
    def validate_base(self):
        if self.artifact_pins.question_artifact_version != (
            "1.0.0" if self.retained_base == "L" else "2.0.0"
        ):
            raise ValueError("Retained base does not match exact native pins")
        return self


class ContinuationRecordReference(StrictEvidenceModel):
    id: UUID
    hash: Sha256


class ContinuationObjectReference(StrictEvidenceModel):
    id: Sha256
    hash: Sha256
