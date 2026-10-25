"""Deterministic selection of source-backed parametric references for Prompt Enrichment."""

from collections import defaultdict

from jewelai_domain.knowledge_base import (
    EstimateKind,
    ParametricKnowledgeBundle,
    ReviewStatus,
)
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_prompts import (
    ParametricEnrichmentReference,
    ParametricReferenceDimensions,
    parametric_reference_context_is_eligible,
)

_KIND_PRIORITY = (
    EstimateKind.APPROXIMATE_CALIBRATION,
    EstimateKind.SOURCE_REFERENCE,
    EstimateKind.STANDARD_PROPORTION_REFERENCE,
)


def select_parametric_references(
    revision: AnyDesignRevision | object,
    catalog: ParametricKnowledgeBundle,
) -> tuple[ParametricEnrichmentReference, ...]:
    """Select exact-context calibrated references without interpolation
    or Product State mutation.
    """

    revision = validate_design_revision(revision)
    catalog = ParametricKnowledgeBundle.model_validate(catalog)
    stone = revision.design.center_stone
    if not parametric_reference_context_is_eligible(revision):
        return ()

    material_id = stone.material.value
    shape_id = stone.shape.value
    weight_ct = stone.weight.value.value
    candidates = tuple(
        item
        for item in catalog.find_calibrations(material_id=material_id, shape_id=shape_id)
        if item.review_status == ReviewStatus.REVIEWED and item.weight_ct == weight_ct
    )
    if not candidates:
        return ()

    selected = ()
    for kind in _KIND_PRIORITY:
        selected = tuple(item for item in candidates if item.estimate_kind == kind)
        if selected:
            break

    by_geometry = defaultdict(list)
    for item in selected:
        dimensions = item.dimensions_mm
        key = (
            dimensions.diameter,
            dimensions.length,
            dimensions.width,
            dimensions.depth,
        )
        by_geometry[key].append(item)

    references = []
    for key in sorted(by_geometry, key=lambda item: tuple(-1.0 if v is None else v for v in item)):
        items = tuple(sorted(by_geometry[key], key=lambda item: item.record_id))
        references.append(
            ParametricEnrichmentReference(
                target="center_stone.dimensions",
                material_id=material_id,
                shape_id=shape_id,
                weight_ct=weight_ct,
                dimensions=ParametricReferenceDimensions(
                    diameter_mm=key[0],
                    length_mm=key[1],
                    width_mm=key[2],
                    depth_mm=key[3],
                ),
                estimate_kind=items[0].estimate_kind.value,
                record_ids=tuple(item.record_id for item in items),
                source_ids=tuple(sorted({item.source_id for item in items})),
                applicability=tuple(sorted({item.applicability for item in items})),
                uncertainty=tuple(sorted({item.uncertainty for item in items})),
            )
        )
    return tuple(references)
