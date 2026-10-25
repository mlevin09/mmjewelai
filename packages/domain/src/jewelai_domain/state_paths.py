"""Stable Product State traversal for Jewelry Design Schema v1.0.0 and v1.1.0."""

from .models import DesignRevision, KnownValue
from .models_v1_1 import DesignRevisionV1_1, validate_design_revision

_BASE_METAL_FIELDS = ("material", "color", "purity", "finish")
_BASE_STONE_FIELDS = (
    "material",
    "shape",
    "cut",
    "weight",
    "dimensions",
    "color",
    "setting",
    "orientation",
)
_BASE_CONSTRUCTION_FIELDS = (
    "shank",
    "gallery",
    "basket",
    "clasp",
    "setting_height",
    "shank_width",
    "thickness",
)
_STONE_V1_1_FIELDS = (
    "variety_or_type",
    "material_origin_status",
    "geographic_origin",
    "treatment_status",
    "treatments",
    "cut_style_class",
)
_SIDE_V1_1_FIELDS = (
    "role",
    "arrangement",
    "location",
    "coverage",
    "total_carat_weight",
    "sieve_system",
    "sieve_designation",
    "diameter_range_mm",
)
_CONSTRUCTION_V1_1_FIELDS = (
    "head",
    "shoulders",
    "bridge",
    "sizing_area",
    "shank_configuration",
    "solidity",
)
_NESTED_CONSTRUCTION_FIELDS = {
    "ring": (
        "size",
        "size_system",
        "inner_diameter_mm",
        "inner_circumference_mm",
        "head_dimensions",
    ),
    "earring": (
        "post_or_wire",
        "back_or_closure",
        "hinge_or_latch",
        "connector",
        "pair_scope",
        "overall_dimensions",
        "drop_length_mm",
        "inside_diameter_mm",
        "outside_diameter_mm",
        "post_length_mm",
        "post_thickness_mm",
    ),
    "pendant": (
        "bail",
        "bail_mobility",
        "connector",
        "overall_dimensions",
        "body_dimensions",
        "bail_inside_dimensions",
        "chain_passage_dimensions",
    ),
    "necklace": (
        "base_type",
        "chain_style",
        "strand_count",
        "strand_progression",
        "end_components",
        "wearable_length_mm",
        "strand_lengths_mm",
    ),
    "bracelet": (
        "structure",
        "hinge",
        "secondary_safety",
        "articulation",
        "wearable_length_mm",
        "inner_circumference_mm",
        "inner_dimensions_mm",
        "width_mm",
        "thickness_mm",
        "cuff_gap_mm",
    ),
    "brooch": (
        "fastening_system",
        "pin_stem",
        "joint",
        "catch",
        "overall_dimensions",
        "thickness_mm",
        "pin_stem_length_mm",
        "fastening_span_mm",
    ),
}


def _known_value(state):
    return state.value if isinstance(state, KnownValue) else None


def iter_knowledge_state_fields(
    revision: DesignRevision | DesignRevisionV1_1 | object,
):
    revision = validate_design_revision(revision)
    design = revision.design
    states = [("jewelry_type", design.jewelry_type)]
    states.extend(
        (f"metal.{name}", getattr(design.metal, name))
        for name in _BASE_METAL_FIELDS
    )
    states.extend(
        (f"center_stone.{name}", getattr(design.center_stone, name))
        for name in _BASE_STONE_FIELDS
    )
    for group in sorted(design.side_stones, key=lambda item: item.group_id):
        prefix = f"side_stones.{group.group_id}"
        states.extend(
            (f"{prefix}.stones.{name}", getattr(group.stones, name))
            for name in _BASE_STONE_FIELDS
        )
        states.append((f"{prefix}.quantity", group.quantity))
    states.extend(
        (f"construction.{name}", getattr(design.construction, name))
        for name in _BASE_CONSTRUCTION_FIELDS
    )
    states.append(("style", design.style))
    if isinstance(revision, DesignRevision):
        return tuple(states)

    states.extend(
        (f"center_stone.{name}", getattr(design.center_stone, name))
        for name in _STONE_V1_1_FIELDS
    )
    for group in sorted(design.side_stones, key=lambda item: item.group_id):
        prefix = f"side_stones.{group.group_id}"
        states.extend(
            (f"{prefix}.stones.{name}", getattr(group.stones, name))
            for name in _STONE_V1_1_FIELDS
        )
        states.extend(
            (f"{prefix}.{name}", getattr(group, name))
            for name in _SIDE_V1_1_FIELDS
        )
    states.extend(
        (f"metal.{name}", getattr(design.metal, name))
        for name in ("alloy_system", "surface_treatment")
    )
    for name in ("material", "coverage", "method", "color_or_effect", "thickness"):
        states.append((f"metal.coating.{name}", getattr(design.metal.coating, name)))
    states.append(("metal.components", design.metal.components))
    components = _known_value(design.metal.components)
    if components is not None:
        for component in sorted(components, key=lambda item: item.component_id):
            prefix = f"metal.components.{component.component_id}"
            for name in (
                "role_or_location",
                "material",
                "color",
                "purity",
                "alloy_system",
                "finish",
                "coating",
                "surface_treatment",
            ):
                states.append((f"{prefix}.{name}", getattr(component, name)))
    states.extend(
        (f"construction.{name}", getattr(design.construction, name))
        for name in _CONSTRUCTION_V1_1_FIELDS
    )
    for section, names in _NESTED_CONSTRUCTION_FIELDS.items():
        obj = getattr(design.construction, section)
        states.extend(
            (f"construction.{section}.{name}", getattr(obj, name))
            for name in names
        )
    states.extend(
        (
            ("prong_count", design.prong_count),
            ("prong_style", design.prong_style),
            ("prong_configuration", design.prong_configuration),
            ("halo.enabled", design.halo.enabled),
            ("halo.type", design.halo.type),
            ("halo.location", design.halo.location),
            ("halo.row_count", design.halo.row_count),
            ("halo.outline_relation", design.halo.outline_relation),
            ("pave.enabled", design.pave.enabled),
            ("pave.location", design.pave.location),
            ("pave.coverage", design.pave.coverage),
            ("pave.row_count", design.pave.row_count),
            ("product.overall_dimensions", design.product.overall_dimensions),
            ("product.dimension_scope", design.product.dimension_scope),
            ("decorative_elements", design.decorative_elements),
            ("composition", design.composition),
            ("style_period_or_movement", design.style_period_or_movement),
            ("style_influences", design.style_influences),
            ("style_descriptors", design.style_descriptors),
        )
    )
    decorative = _known_value(design.decorative_elements)
    if decorative is not None:
        for item in sorted(decorative, key=lambda value: value.element_id):
            prefix = f"decorative_elements.{item.element_id}"
            for name in ("technique", "motif", "location", "prominence"):
                states.append((f"{prefix}.{name}", getattr(item, name)))
    composition = _known_value(design.composition)
    if composition is not None:
        for name in (
            "symmetry_mode",
            "organization",
            "focal_hierarchy",
            "negative_space_intent",
            "rhythm",
        ):
            states.append((f"composition.{name}", getattr(composition, name)))
    return tuple(states)


def iter_prompt_state_fields(
    revision: DesignRevision | DesignRevisionV1_1 | object,
):
    revision = validate_design_revision(revision)
    states = list(iter_knowledge_state_fields(revision))
    states.extend(
        (
            ("references", revision.design.references),
            ("visual_constraints", revision.design.visual_constraints),
        )
    )
    return tuple(states)
