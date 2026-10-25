"""Runtime models for frozen Visualization Verification Result Contract v1.0.0."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .models import ImmutableModel

VISUALIZATION_VERIFICATION_CONTRACT_VERSION = "1.0.0"
NonEmpty = Annotated[str, StringConstraints(min_length=1)]
Confidence = Annotated[float, Field(ge=0, le=1)]


class VerificationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIABLE = "UNVERIFIABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class VerificationSeverity(StrEnum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class VerificationAction(StrEnum):
    ACCEPT = "ACCEPT"
    RETRY = "RETRY"
    ASK = "ASK"
    CAD_3D_FALLBACK = "CAD_3D_FALLBACK"
    DO_NOT_CLAIM = "DO_NOT_CLAIM"


class VerificationDimension(StrEnum):
    PRODUCT_STATE_FIDELITY = "product_state_fidelity"
    GEOMETRY_PROPORTION_FIDELITY = "geometry_proportion_fidelity"
    STRUCTURAL_PLAUSIBILITY = "structural_plausibility"
    SETTING_STONE_RELATIONSHIP = "setting_stone_relationship"
    GEMSTONE_APPEARANCE_PLAUSIBILITY = "gemstone_appearance_plausibility"
    METAL_FINISH_PLAUSIBILITY = "metal_finish_plausibility"
    EDIT_IDENTITY_PRESERVATION = "edit_identity_preservation"
    REFERENCE_FIDELITY = "reference_fidelity"
    CROSS_VIEW_CONSISTENCY = "cross_view_consistency"
    PRESENTATION_SCENE_PLAUSIBILITY = "presentation_scene_plausibility"
    OUTPUT_PROFILE_USABILITY = "output_profile_usability"
    OBSERVABILITY_CONFIDENCE = "observability_confidence"


class VerificationSubject(ImmutableModel):
    generation_run_id: NonEmpty
    asset_id: str | None = None
    design_revision_id: str | None = None
    previous_asset_id: str | None = None


class VerificationCheck(ImmutableModel):
    check_id: NonEmpty
    dimension: VerificationDimension
    status: VerificationStatus
    severity: VerificationSeverity | None = None
    feature_path: str | None = None
    error_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    confidence: Confidence | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_unique_error_ids(self):
        if len(set(self.error_ids)) != len(self.error_ids):
            raise ValueError("verification check error_ids must be unique")
        return self


class VisualizationVerificationResult(ImmutableModel):
    contract_version: Literal["1.0.0"] = (
        VISUALIZATION_VERIFICATION_CONTRACT_VERSION
    )
    verification_id: NonEmpty
    subject: VerificationSubject
    overall_status: VerificationStatus
    action: VerificationAction
    checks: Annotated[tuple[VerificationCheck, ...], Field(min_length=1)]
    error_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self):
        check_ids = [item.check_id for item in self.checks]
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("verification check IDs must be unique")
        if len(set(self.error_ids)) != len(self.error_ids):
            raise ValueError("verification result error_ids must be unique")
        return self
