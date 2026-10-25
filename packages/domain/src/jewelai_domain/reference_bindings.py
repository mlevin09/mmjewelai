"""Runtime models for frozen Reference Binding Contract v1.0.0."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, model_validator

from .models import ImmutableModel

REFERENCE_BINDING_CONTRACT_VERSION = "1.0.0"
NonEmpty = Annotated[str, StringConstraints(min_length=1)]
Confidence = Annotated[float, Field(ge=0, le=1)]


class ReferenceRelation(StrEnum):
    KEEP = "KEEP"
    CHANGE = "CHANGE"
    LOCKED = "LOCKED"
    INSPIRATION = "INSPIRATION"
    UNKNOWN = "UNKNOWN"


class ReferenceRole(StrEnum):
    BASE_DESIGN = "base_design"
    FEATURE_DONOR = "feature_donor"
    STYLE_INSPIRATION = "style_inspiration"
    EXISTING_PRODUCT_CONSTRAINT = "existing_product_constraint"
    COMPANION_PRODUCT = "companion_product"
    STONE_REFERENCE = "stone_reference"
    SETTING_REFERENCE = "setting_reference"
    PROPORTION_REFERENCE = "proportion_reference"
    MATERIAL_COLOR_REFERENCE = "material_color_reference"
    COMPOSITION_REFERENCE = "composition_reference"
    PRESENTATION_REFERENCE = "presentation_reference"
    COMPARISON_REFERENCE = "comparison_reference"


class ReferenceProvenance(StrEnum):
    USER_TEXT = "user_text"
    VOICE = "voice"
    CONFIRMED_CONTEXT = "confirmed_context"
    SYSTEM_STATE = "system_state"
    IMAGE_DERIVED_OBSERVATION = "image_derived_observation"


class ReferenceObservability(StrEnum):
    EXPLICIT = "EXPLICIT"
    OBSERVABLE = "OBSERVABLE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    UNVERIFIABLE = "UNVERIFIABLE"


class PresentationParameter(StrEnum):
    CAMERA_VIEW = "camera_view"
    FRAMING = "framing"
    LIGHTING = "lighting"
    BACKGROUND = "background"
    RENDER_CONTEXT = "render_context"
    SCALE_INSTRUCTION = "scale_instruction"


class FeatureBinding(ImmutableModel):
    feature_path: NonEmpty
    relation: ReferenceRelation
    target: JsonValue = None
    raw_user_language: str | None = None
    provenance: ReferenceProvenance
    confidence: Confidence | None = None
    observability: ReferenceObservability | None = Field(\n        default=None, exclude_if=lambda value: value is None\n    )


class PresentationBinding(ImmutableModel):
    parameter: PresentationParameter
    relation: ReferenceRelation
    value: JsonValue = None


class ReferenceBinding(ImmutableModel):
    contract_version: Literal["1.0.0"] = REFERENCE_BINDING_CONTRACT_VERSION
    binding_id: NonEmpty
    asset_id: NonEmpty
    reference_role: ReferenceRole
    feature_bindings: Annotated[tuple[FeatureBinding, ...], Field(min_length=1)]
    presentation_bindings: tuple[PresentationBinding, ...] = ()

    @model_validator(mode="after")
    def validate_deterministic_bindings(self):
        feature_keys = [
            (item.feature_path, item.relation.value)
            for item in self.feature_bindings
        ]
        if len(set(feature_keys)) != len(feature_keys):
            raise ValueError(
                "feature bindings must be unique by feature_path and relation"
            )
        presentation_keys = [
            (item.parameter.value, item.relation.value)
            for item in self.presentation_bindings
        ]
        if len(set(presentation_keys)) != len(presentation_keys):
            raise ValueError(
                "presentation bindings must be unique by parameter and relation"
            )
        return self
