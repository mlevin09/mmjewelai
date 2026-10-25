"""Jewelry Design Schema v1.1.0 additive runtime contract."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .models import (
    AssetReference,
    DesignRevision,
    Dimensions,
    DomainId,
    FinenessPurity,
    ImmutableModel,
    KaratPurity,
    Length,
    RevisionEvent,
    State,
    StoneQuantity,
    Text,
    VisualConstraint,
    Weight,
)

SCHEMA_VERSION_V1_1 = "1.1.0"
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class TwoDimensionalSize(ImmutableModel):
    length: Length
    width: Length


class DiameterRange(ImmutableModel):
    minimum: Length
    maximum: Length

    @model_validator(mode="after")
    def validate_order(self):
        if self.minimum.value > self.maximum.value:
            raise ValueError("diameter range minimum cannot exceed maximum")
        return self


class CoatingV1_1(ImmutableModel):
    material: State[DomainId] | None = None
    coverage: State[DomainId] | None = None
    method: State[DomainId] | None = None
    color_or_effect: State[DomainId] | None = None
    thickness: State[Length] | None = None


class MetalComponentV1_1(ImmutableModel):
    component_id: DomainId
    role_or_location: State[DomainId] | None = None
    material: State[DomainId] | None = None
    color: State[DomainId] | None = None
    purity: State[KaratPurity | FinenessPurity] | None = None
    alloy_system: State[DomainId] | None = None
    finish: State[DomainId] | None = None
    coating: State[CoatingV1_1] | None = None
    surface_treatment: State[DomainId] | None = None


class MetalV1_1(ImmutableModel):
    material: State[DomainId] | None = None
    color: State[DomainId] | None = None
    purity: State[KaratPurity | FinenessPurity] | None = None
    finish: State[DomainId] | None = None
    alloy_system: State[DomainId] | None = None
    coating: CoatingV1_1 = Field(default_factory=CoatingV1_1)
    surface_treatment: State[DomainId] | None = None
    components: State[tuple[MetalComponentV1_1, ...]] | None = None

    @model_validator(mode="after")
    def unique_components(self):
        if self.components is not None and getattr(self.components, "availability", None) == "value":
            ids = [item.component_id for item in self.components.value]
            if len(set(ids)) != len(ids):
                raise ValueError("metal component IDs must be unique")
        return self


class StoneV1_1(ImmutableModel):
    material: State[DomainId] | None = None
    shape: State[DomainId] | None = None
    cut: State[DomainId] | None = None
    weight: State[Weight] | None = None
    dimensions: State[Dimensions] | None = None
    color: State[Text] | None = None
    setting: State[DomainId] | None = None
    orientation: State[DomainId] | None = None
    variety_or_type: State[DomainId] | None = None
    material_origin_status: State[DomainId] | None = None
    geographic_origin: State[Text] | None = None
    treatment_status: State[DomainId] | None = None
    treatments: State[tuple[DomainId, ...]] | None = None
    cut_style_class: State[DomainId] | None = None


class SideStoneGroupV1_1(ImmutableModel):
    group_id: DomainId
    stones: StoneV1_1
    quantity: State[StoneQuantity] | None = None
    role: State[DomainId] | None = None
    arrangement: State[DomainId] | None = None
    location: State[DomainId] | None = None
    coverage: State[DomainId] | None = None
    total_carat_weight: State[Weight] | None = None
    sieve_system: State[DomainId] | None = None
    sieve_designation: State[Text] | None = None
    diameter_range_mm: State[DiameterRange] | None = None


class HaloV1_1(ImmutableModel):
    enabled: State[bool] | None = None
    type: State[DomainId] | None = None
    location: State[DomainId] | None = None
    row_count: State[PositiveInt] | None = None
    outline_relation: State[DomainId] | None = None


class PaveV1_1(ImmutableModel):
    enabled: State[bool] | None = None
    location: State[DomainId] | None = None
    coverage: State[DomainId] | None = None
    row_count: State[PositiveInt] | None = None


class RingConstructionV1_1(ImmutableModel):
    size: State[Text] | None = None
    size_system: State[DomainId] | None = None
    inner_diameter_mm: State[Length] | None = None
    inner_circumference_mm: State[Length] | None = None
    head_dimensions: State[Dimensions | TwoDimensionalSize] | None = None


class EarringConstructionV1_1(ImmutableModel):
    post_or_wire: State[DomainId] | None = None
    back_or_closure: State[DomainId] | None = None
    hinge_or_latch: State[DomainId] | None = None
    connector: State[DomainId] | None = None
    pair_scope: State[DomainId] | None = None
    overall_dimensions: State[Dimensions | TwoDimensionalSize] | None = None
    drop_length_mm: State[Length] | None = None
    inside_diameter_mm: State[Length] | None = None
    outside_diameter_mm: State[Length] | None = None
    post_length_mm: State[Length] | None = None
    post_thickness_mm: State[Length] | None = None


class PendantConstructionV1_1(ImmutableModel):
    bail: State[DomainId] | None = None
    bail_mobility: State[DomainId] | None = None
    connector: State[DomainId] | None = None
    overall_dimensions: State[Dimensions | TwoDimensionalSize] | None = None
    body_dimensions: State[Dimensions | TwoDimensionalSize] | None = None
    bail_inside_dimensions: State[TwoDimensionalSize] | None = None
    chain_passage_dimensions: State[TwoDimensionalSize] | None = None


class NecklaceConstructionV1_1(ImmutableModel):
    base_type: State[DomainId] | None = None
    chain_style: State[DomainId] | None = None
    strand_count: State[PositiveInt] | None = None
    strand_progression: State[DomainId] | None = None
    end_components: State[tuple[DomainId, ...]] | None = None
    wearable_length_mm: State[Length] | None = None
    strand_lengths_mm: State[tuple[Length, ...]] | None = None


class BraceletConstructionV1_1(ImmutableModel):
    structure: State[DomainId] | None = None
    hinge: State[DomainId] | None = None
    secondary_safety: State[DomainId] | None = None
    articulation: State[DomainId] | None = None
    wearable_length_mm: State[Length] | None = None
    inner_circumference_mm: State[Length] | None = None
    inner_dimensions_mm: State[TwoDimensionalSize] | None = None
    width_mm: State[Length] | None = None
    thickness_mm: State[Length] | None = None
    cuff_gap_mm: State[Length] | None = None


class BroochConstructionV1_1(ImmutableModel):
    fastening_system: State[DomainId] | None = None
    pin_stem: State[DomainId] | None = None
    joint: State[DomainId] | None = None
    catch: State[DomainId] | None = None
    overall_dimensions: State[Dimensions | TwoDimensionalSize] | None = None
    thickness_mm: State[Length] | None = None
    pin_stem_length_mm: State[Length] | None = None
    fastening_span_mm: State[Length] | None = None


class ConstructionV1_1(ImmutableModel):
    shank: State[DomainId] | None = None
    gallery: State[DomainId] | None = None
    basket: State[DomainId] | None = None
    clasp: State[DomainId] | None = None
    setting_height: State[Length] | None = None
    shank_width: State[Length] | None = None
    thickness: State[Length] | None = None
    head: State[DomainId] | None = None
    shoulders: State[DomainId] | None = None
    bridge: State[DomainId] | None = None
    sizing_area: State[DomainId] | None = None
    shank_configuration: State[DomainId] | None = None
    solidity: State[DomainId] | None = None
    ring: RingConstructionV1_1 = Field(default_factory=RingConstructionV1_1)
    earring: EarringConstructionV1_1 = Field(default_factory=EarringConstructionV1_1)
    pendant: PendantConstructionV1_1 = Field(default_factory=PendantConstructionV1_1)
    necklace: NecklaceConstructionV1_1 = Field(default_factory=NecklaceConstructionV1_1)
    bracelet: BraceletConstructionV1_1 = Field(default_factory=BraceletConstructionV1_1)
    brooch: BroochConstructionV1_1 = Field(default_factory=BroochConstructionV1_1)


class ProductDimensionsV1_1(ImmutableModel):
    overall_dimensions: State[Dimensions | TwoDimensionalSize] | None = None
    dimension_scope: State[DomainId] | None = None


class DecorativeElementV1_1(ImmutableModel):
    element_id: DomainId
    technique: State[DomainId] | None = None
    motif: State[DomainId] | None = None
    location: State[DomainId] | None = None
    prominence: State[DomainId] | None = None


class CompositionV1_1(ImmutableModel):
    symmetry_mode: State[DomainId] | None = None
    organization: State[DomainId] | None = None
    focal_hierarchy: State[DomainId] | None = None
    negative_space_intent: State[DomainId] | None = None
    rhythm: State[DomainId] | None = None


class DesignV1_1(ImmutableModel):
    jewelry_type: State[DomainId] | None = None
    metal: MetalV1_1 = Field(default_factory=MetalV1_1)
    center_stone: StoneV1_1 = Field(default_factory=StoneV1_1)
    side_stones: tuple[SideStoneGroupV1_1, ...] = ()
    construction: ConstructionV1_1 = Field(default_factory=ConstructionV1_1)
    style: State[tuple[DomainId, ...]] | None = None
    references: State[tuple[AssetReference, ...]] | None = None
    visual_constraints: State[tuple[VisualConstraint, ...]] | None = None
    prong_count: State[PositiveInt] | None = None
    prong_style: State[DomainId] | None = None
    prong_configuration: State[DomainId] | None = None
    halo: HaloV1_1 = Field(default_factory=HaloV1_1)
    pave: PaveV1_1 = Field(default_factory=PaveV1_1)
    product: ProductDimensionsV1_1 = Field(default_factory=ProductDimensionsV1_1)
    decorative_elements: State[tuple[DecorativeElementV1_1, ...]] | None = None
    composition: State[CompositionV1_1] | None = None
    style_period_or_movement: State[DomainId] | None = None
    style_influences: State[tuple[DomainId, ...]] | None = None
    style_descriptors: State[tuple[DomainId, ...]] | None = None

    @model_validator(mode="after")
    def validate_stable_ids(self):
        group_ids = [group.group_id for group in self.side_stones]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("Side stone group IDs must be unique")
        if (
            self.decorative_elements is not None
            and getattr(self.decorative_elements, "availability", None) == "value"
        ):
            ids = [item.element_id for item in self.decorative_elements.value]
            if len(set(ids)) != len(ids):
                raise ValueError("decorative element IDs must be unique")
        return self


class DesignRevisionV1_1(ImmutableModel):
    schema_version: Literal["1.1.0"] = SCHEMA_VERSION_V1_1
    design_id: UUID
    revision_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    parent_revision_id: UUID | None = None
    created_at: AwareDatetime
    event: RevisionEvent
    design: DesignV1_1

    @model_validator(mode="after")
    def validate_lineage(self):
        if (self.revision == 1) != (self.parent_revision_id is None):
            raise ValueError("Only revision 1 may have no parent")
        if (self.revision == 1) != (self.event.action == "create"):
            raise ValueError("Only revision 1 may have a create event")
        if self.parent_revision_id == self.revision_id:
            raise ValueError("A revision cannot be its own parent")
        if self.event.source.recorded_at > self.created_at:
            raise ValueError("Event source cannot be later than the revision")
        return self


type AnyDesignRevision = DesignRevision | DesignRevisionV1_1


def validate_design_revision(value: object) -> AnyDesignRevision:
    if isinstance(value, DesignRevisionV1_1):
        return DesignRevisionV1_1.model_validate(value)
    if isinstance(value, DesignRevision):
        return DesignRevision.model_validate(value)
    schema_version = (
        value.get("schema_version")
        if isinstance(value, dict)
        else getattr(value, "schema_version", None)
    )
    if schema_version == "1.1.0":
        return DesignRevisionV1_1.model_validate(value)
    if schema_version == "1.0.0":
        return DesignRevision.model_validate(value)
    raise ValueError(f"unsupported jewelry design schema_version: {schema_version!r}")


def upgrade_design_revision_v1_to_v1_1(
    revision: DesignRevision | object,
) -> DesignRevisionV1_1:
    revision = DesignRevision.model_validate(revision)
    payload = revision.model_dump(mode="json")
    payload["schema_version"] = "1.1.0"
    return DesignRevisionV1_1.model_validate(payload)


def snapshot_json_v1_1(revision: DesignRevisionV1_1 | object) -> str:
    return DesignRevisionV1_1.model_validate(revision).model_dump_json(indent=2)


def migrate_design_revision_v1_to_v1_1(
    revision: DesignRevision | object,
    *,
    revision_id: UUID,
    created_at: AwareDatetime,
    source,
    reason: str,
) -> DesignRevisionV1_1:
    """Create a new immutable v1.1 revision that continues a v1.0 lineage."""
    revision = DesignRevision.model_validate(revision)
    payload = revision.design.model_dump(mode="json")
    return DesignRevisionV1_1(
        schema_version="1.1.0",
        design_id=revision.design_id,
        revision_id=revision_id,
        revision=revision.revision + 1,
        parent_revision_id=revision.revision_id,
        created_at=created_at,
        event=RevisionEvent(
            action="edit",
            source=source,
            reason=reason,
        ),
        design=DesignV1_1.model_validate(payload),
    )
