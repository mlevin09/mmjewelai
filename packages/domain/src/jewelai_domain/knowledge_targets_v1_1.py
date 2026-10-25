"""Frozen Jewelry Design Schema v1.1.0 target grammar for Knowledge runtime.

This module does not alter Knowledge Library Contract v1.0.0. It provides the
versioned 1.1 target registry and stable collection-token normalization needed by
a future v1.1 Knowledge Library catalog/runtime.
"""

import re

SCHEMA_TARGET_VERSION_V1_1 = "1.1.0"

PRODUCT_STATE_TARGET_FAMILIES_V1_1 = frozenset(
    (
        "jewelry_type",
        "metal.material",
        "metal.color",
        "metal.purity",
        "metal.finish",
        "center_stone.material",
        "center_stone.shape",
        "center_stone.cut",
        "center_stone.weight",
        "center_stone.dimensions",
        "center_stone.color",
        "center_stone.setting",
        "center_stone.orientation",
        "construction.shank",
        "construction.gallery",
        "construction.basket",
        "construction.clasp",
        "construction.setting_height",
        "construction.shank_width",
        "construction.thickness",
        "style",
        "side_stones.{group_id}.stones.material",
        "side_stones.{group_id}.stones.shape",
        "side_stones.{group_id}.stones.cut",
        "side_stones.{group_id}.stones.weight",
        "side_stones.{group_id}.stones.dimensions",
        "side_stones.{group_id}.stones.color",
        "side_stones.{group_id}.stones.setting",
        "side_stones.{group_id}.stones.orientation",
        "side_stones.{group_id}.quantity",
        "prong_count",
        "prong_style",
        "side_stones.{group_id}.role",
        "side_stones.{group_id}.arrangement",
        "side_stones.{group_id}.location",
        "side_stones.{group_id}.coverage",
        "halo.enabled",
        "halo.type",
        "pave.enabled",
        "pave.location",
        "pave.coverage",
        "decorative_elements",
        "composition",
        "side_stones.{group_id}.sieve_system",
        "side_stones.{group_id}.sieve_designation",
        "side_stones.{group_id}.diameter_range_mm",
        "center_stone.variety_or_type",
        "side_stones.{group_id}.stones.variety_or_type",
        "center_stone.material_origin_status",
        "side_stones.{group_id}.stones.material_origin_status",
        "center_stone.geographic_origin",
        "side_stones.{group_id}.stones.geographic_origin",
        "center_stone.treatment_status",
        "side_stones.{group_id}.stones.treatment_status",
        "center_stone.treatments",
        "side_stones.{group_id}.stones.treatments",
        "center_stone.cut_style_class",
        "side_stones.{group_id}.stones.cut_style_class",
        "prong_configuration",
        "side_stones.{group_id}.total_carat_weight",
        "halo.location",
        "halo.row_count",
        "halo.outline_relation",
        "pave.row_count",
        "metal.alloy_system",
        "metal.coating.material",
        "metal.coating.coverage",
        "metal.coating.method",
        "metal.coating.color_or_effect",
        "metal.coating.thickness",
        "metal.surface_treatment",
        "metal.components",
        "metal.components[].role_or_location",
        "metal.components[].material",
        "metal.components[].color",
        "metal.components[].purity",
        "metal.components[].alloy_system",
        "metal.components[].finish",
        "metal.components[].coating",
        "metal.components[].surface_treatment",
        "construction.head",
        "construction.shoulders",
        "construction.bridge",
        "construction.sizing_area",
        "construction.shank_configuration",
        "construction.solidity",
        "construction.earring.post_or_wire",
        "construction.earring.back_or_closure",
        "construction.earring.hinge_or_latch",
        "construction.earring.connector",
        "construction.earring.pair_scope",
        "construction.pendant.bail",
        "construction.pendant.bail_mobility",
        "construction.pendant.connector",
        "construction.necklace.base_type",
        "construction.necklace.chain_style",
        "construction.necklace.strand_count",
        "construction.necklace.strand_progression",
        "construction.necklace.end_components",
        "construction.bracelet.structure",
        "construction.bracelet.hinge",
        "construction.bracelet.secondary_safety",
        "construction.bracelet.articulation",
        "construction.brooch.fastening_system",
        "construction.brooch.pin_stem",
        "construction.brooch.joint",
        "construction.brooch.catch",
        "product.overall_dimensions",
        "product.dimension_scope",
        "construction.ring.size",
        "construction.ring.size_system",
        "construction.ring.inner_diameter_mm",
        "construction.ring.inner_circumference_mm",
        "construction.ring.head_dimensions",
        "construction.earring.overall_dimensions",
        "construction.earring.drop_length_mm",
        "construction.earring.inside_diameter_mm",
        "construction.earring.outside_diameter_mm",
        "construction.earring.post_length_mm",
        "construction.earring.post_thickness_mm",
        "construction.pendant.overall_dimensions",
        "construction.pendant.body_dimensions",
        "construction.pendant.bail_inside_dimensions",
        "construction.pendant.chain_passage_dimensions",
        "construction.necklace.wearable_length_mm",
        "construction.necklace.strand_lengths_mm",
        "construction.bracelet.wearable_length_mm",
        "construction.bracelet.inner_circumference_mm",
        "construction.bracelet.inner_dimensions_mm",
        "construction.bracelet.width_mm",
        "construction.bracelet.thickness_mm",
        "construction.bracelet.cuff_gap_mm",
        "construction.brooch.overall_dimensions",
        "construction.brooch.thickness_mm",
        "construction.brooch.pin_stem_length_mm",
        "construction.brooch.fastening_span_mm",
        "style_period_or_movement",
        "style_influences",
        "style_descriptors",
        "decorative_elements[].technique",
        "decorative_elements[].motif",
        "decorative_elements[].location",
        "decorative_elements[].prominence",
        "composition.symmetry_mode",
        "composition.organization",
        "composition.focal_hierarchy",
        "composition.negative_space_intent",
        "composition.rhythm",
    )
)

_DOMAIN_ID = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def policy_template_for_family(family: str) -> str:
    if family.startswith("metal.components[]."):
        return family.replace("metal.components[]", "metal.components.{component_id}", 1)
    if family.startswith("decorative_elements[]."):
        return family.replace("decorative_elements[]", "decorative_elements.{element_id}", 1)
    return family


POLICY_TARGET_TEMPLATES_V1_1 = frozenset(
    policy_template_for_family(item) for item in PRODUCT_STATE_TARGET_FAMILIES_V1_1
)


def target_family_from_concrete(target: str) -> str | None:
    if target in PRODUCT_STATE_TARGET_FAMILIES_V1_1:
        return target
    parts = target.split(".")
    if len(parts) >= 3 and parts[0] == "side_stones" and _DOMAIN_ID.fullmatch(parts[1]):
        family = ".".join(("side_stones", "{group_id}", *parts[2:]))
        return family if family in PRODUCT_STATE_TARGET_FAMILIES_V1_1 else None
    if len(parts) >= 3 and parts[:2] == ["metal", "components"] and _DOMAIN_ID.fullmatch(parts[2]):
        family = "metal.components[]" + ("." + ".".join(parts[3:]) if len(parts) > 3 else "")
        return family if family in PRODUCT_STATE_TARGET_FAMILIES_V1_1 else None
    if len(parts) >= 2 and parts[0] == "decorative_elements" and _DOMAIN_ID.fullmatch(parts[1]):
        family = "decorative_elements[]" + ("." + ".".join(parts[2:]) if len(parts) > 2 else "")
        return family if family in PRODUCT_STATE_TARGET_FAMILIES_V1_1 else None
    return None


def is_allowed_product_state_target_v1_1(target: str) -> bool:
    return target_family_from_concrete(target) is not None
