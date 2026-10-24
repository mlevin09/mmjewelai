"""Source-backed limited quantitative gemstone knowledge base.

This module deliberately keeps quantitative reference data separate from the semantic Knowledge
Library. Carat weight remains mass; calibrated dimensions are approximate reference points, never
measured manufacturing facts.
"""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .models import ImmutableModel, Version

KNOWLEDGE_BASE_SCHEMA_VERSION = "1.0.0"

RecordId = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9_.-]+$")]
DomainId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]*$")]


class KnowledgeBaseValidationError(ValueError):
    """Raised when a quantitative knowledge artifact is internally inconsistent."""


class ReviewStatus(StrEnum):
    REVIEWED = "REVIEWED"
    DRAFT = "DRAFT"
    REJECTED = "REJECTED"


class EvidenceTier(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    CORROBORATIVE = "CORROBORATIVE"


class EstimateKind(StrEnum):
    SOURCE_REFERENCE = "SOURCE_REFERENCE"
    APPROXIMATE_CALIBRATION = "APPROXIMATE_CALIBRATION"
    STANDARD_PROPORTION_REFERENCE = "STANDARD_PROPORTION_REFERENCE"


class ParametricSource(ImmutableModel):
    source_id: RecordId
    title: Annotated[str, StringConstraints(min_length=1)]
    uri: Annotated[str, StringConstraints(min_length=1)]
    evidence_tier: EvidenceTier
    source_version: str | None = None
    retrieved_on: str | None = None
    review_status: ReviewStatus = ReviewStatus.REVIEWED


class SpecificGravityRecord(ImmutableModel):
    record_id: RecordId
    material_id: DomainId
    nominal: float = Field(gt=0)
    minimum: float | None = Field(default=None, gt=0)
    maximum: float | None = Field(default=None, gt=0)
    source_id: RecordId
    applicability: Annotated[str, StringConstraints(min_length=1)]
    uncertainty: Annotated[str, StringConstraints(min_length=1)]
    review_status: ReviewStatus = ReviewStatus.REVIEWED

    @model_validator(mode="after")
    def validate_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("specific-gravity minimum cannot exceed maximum")
        if self.minimum is not None and self.nominal < self.minimum:
            raise ValueError("specific-gravity nominal cannot be below minimum")
        if self.maximum is not None and self.nominal > self.maximum:
            raise ValueError("specific-gravity nominal cannot exceed maximum")
        return self


class DimensionsMm(ImmutableModel):
    diameter: float | None = Field(default=None, gt=0)
    length: float | None = Field(default=None, gt=0)
    width: float | None = Field(default=None, gt=0)
    depth: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_geometry(self):
        round_geometry = self.diameter is not None
        fancy_geometry = self.length is not None or self.width is not None
        if round_geometry and fancy_geometry:
            raise ValueError("dimensions must use diameter or length/width, not both")
        if not round_geometry and not (self.length is not None and self.width is not None):
            raise ValueError("dimensions require diameter or both length and width")
        return self


class CalibratedSizeWeightRecord(ImmutableModel):
    record_id: RecordId
    material_id: DomainId
    shape_id: DomainId
    weight_ct: float = Field(gt=0)
    dimensions_mm: DimensionsMm
    estimate_kind: EstimateKind
    source_id: RecordId
    applicability: Annotated[str, StringConstraints(min_length=1)]
    uncertainty: Annotated[str, StringConstraints(min_length=1)]
    review_status: ReviewStatus = ReviewStatus.REVIEWED

    @model_validator(mode="after")
    def reject_exactness_claim(self):
        lowered = self.uncertainty.casefold()
        if "exact" in lowered or "measured" in lowered:
            raise ValueError(\n                "calibrated size/weight records cannot claim exact measured dimensions"\n            )
        return self


class ParametricKnowledgeBundle(ImmutableModel):
    schema_version: Literal["1.0.0"] = KNOWLEDGE_BASE_SCHEMA_VERSION
    catalog_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]+$")]
    artifact_version: Version
    sources: tuple[ParametricSource, ...]
    specific_gravity: tuple[SpecificGravityRecord, ...] = ()
    calibrated_size_weight: tuple[CalibratedSizeWeightRecord, ...] = ()

    @model_validator(mode="after")
    def validate_references_and_ids(self):
        sources = {item.source_id for item in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("duplicate parametric source IDs")

        records = [item.record_id for item in self.specific_gravity]
        records.extend(item.record_id for item in self.calibrated_size_weight)
        if len(records) != len(set(records)):
            raise ValueError("duplicate parametric record IDs")

        for item in (*self.specific_gravity, *self.calibrated_size_weight):
            if item.source_id not in sources:
                raise ValueError(
                    f"parametric record {item.record_id} references unknown source {item.source_id}"
                )
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def find_calibrations(
        self,
        *,
        material_id: str | None = None,
        shape_id: str | None = None,
    ) -> tuple[CalibratedSizeWeightRecord, ...]:
        values = self.calibrated_size_weight
        if material_id is not None:
            values = tuple(item for item in values if item.material_id == material_id)
        if shape_id is not None:
            values = tuple(item for item in values if item.shape_id == shape_id)
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.material_id,
                    item.shape_id,
                    item.weight_ct,
                    item.record_id,
                ),
            )
        )


def validate_parametric_knowledge(data) -> ParametricKnowledgeBundle:
    """Validate one immutable quantitative catalog."""
    try:
        return ParametricKnowledgeBundle.model_validate(data)
    except ValueError as exc:
        raise KnowledgeBaseValidationError(str(exc)) from exc


def load_parametric_knowledge(path: str | Path) -> ParametricKnowledgeBundle:
    """Load and validate one UTF-8 JSON quantitative catalog."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_parametric_knowledge(payload)
