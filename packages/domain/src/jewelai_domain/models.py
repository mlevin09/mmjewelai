"""Immutable snapshot contracts. Business readiness belongs to the later rules engine."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION = "1.0.0"
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000, pattern=r"\S")]
DomainId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
Positive = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]


class ImmutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class MessageSource(ImmutableModel):
    kind: Literal["message"] = "message"
    message_id: Text
    recorded_at: AwareDatetime


class KnowledgeSource(ImmutableModel):
    kind: Literal["knowledge"] = "knowledge"
    record_id: Text
    version: Version
    recorded_at: AwareDatetime


class RuleSource(ImmutableModel):
    kind: Literal["rule"] = "rule"
    rule_id: Text
    version: Version
    recorded_at: AwareDatetime


class Unknown(ImmutableModel):
    availability: Literal["unknown"] = "unknown"
    origin: Literal["unknown"] = "unknown"
    requirement: Literal["required", "optional", "undetermined"] = "undetermined"
    value: None = None
    confirmed: Literal[False] = False
    locked: Literal[False] = False


class NotApplicable(ImmutableModel):
    availability: Literal["not_applicable"] = "not_applicable"
    origin: Literal["explicit"] = "explicit"
    value: None = None
    reason: Text
    source: MessageSource
    confirmed: Literal[True] = True
    locked: StrictBool = False


LOCK_CONDITION = {
    "if": {"properties": {"locked": {"const": True}}, "required": ["locked"]},
    "then": {"properties": {"confirmed": {"const": True}}, "required": ["confirmed"]},
}


class KnownValue[T](ImmutableModel):
    model_config = ConfigDict(json_schema_extra={"allOf": [LOCK_CONDITION]})
    availability: Literal["value"] = "value"
    value: T
    confirmed: StrictBool = False
    locked: StrictBool = False

    @model_validator(mode="after")
    def validate_lock(self):
        if self.locked and not self.confirmed:
            raise ValueError("A locked value must be confirmed first")
        return self


class Explicit[T](KnownValue[T]):
    origin: Literal["explicit"] = "explicit"
    source: MessageSource


class Derived[T](KnownValue[T]):
    origin: Literal["derived"] = "derived"
    sources: Annotated[tuple[KnowledgeSource | RuleSource, ...], Field(min_length=1)]
    uncertainty: Text


class Assumed[T](KnownValue[T]):
    origin: Literal["assumed"] = "assumed"
    source: RuleSource
    rationale: Text


# Availability/origin literals make the five variants mutually exclusive on the wire.
type State[T] = Unknown | NotApplicable | Explicit[T] | Derived[T] | Assumed[T]


class Length(ImmutableModel):
    value: Positive
    unit: Literal["mm"] = "mm"


class Weight(ImmutableModel):
    value: Positive
    unit: Literal["ct"] = "ct"


class Dimensions(ImmutableModel):
    length: Length
    width: Length
    depth: Length


class KaratPurity(ImmutableModel):
    value: Annotated[float, Field(strict=True, gt=0, le=24, allow_inf_nan=False)]
    unit: Literal["karat"] = "karat"


class FinenessPurity(ImmutableModel):
    value: Annotated[int, Field(strict=True, gt=0, le=1000)]
    unit: Literal["fineness"] = "fineness"


class StoneQuantity(ImmutableModel):
    value: Annotated[int, Field(strict=True, gt=0)]
    scope: Literal["per_side", "per_item", "per_pair"]


class Metal(ImmutableModel):
    material: State[DomainId] | None = None
    color: State[DomainId] | None = None
    purity: State[KaratPurity | FinenessPurity] | None = None
    finish: State[DomainId] | None = None


class Stone(ImmutableModel):
    material: State[DomainId] | None = None
    shape: State[DomainId] | None = None
    cut: State[DomainId] | None = None
    weight: State[Weight] | None = None
    dimensions: State[Dimensions] | None = None
    color: State[Text] | None = None
    setting: State[DomainId] | None = None
    orientation: State[DomainId] | None = None


class SideStoneGroup(ImmutableModel):
    group_id: DomainId
    stones: Stone
    quantity: State[StoneQuantity] | None = None


class Construction(ImmutableModel):
    shank: State[DomainId] | None = None
    gallery: State[DomainId] | None = None
    basket: State[DomainId] | None = None
    clasp: State[DomainId] | None = None
    setting_height: State[Length] | None = None
    shank_width: State[Length] | None = None
    thickness: State[Length] | None = None


class AssetReference(ImmutableModel):
    asset_id: Text
    purpose: Literal["design", "material", "style", "proportion"]
    note: Text | None = None


class VisualConstraint(ImmutableModel):
    constraint_id: DomainId
    instruction: Text


class Design(ImmutableModel):
    jewelry_type: State[DomainId] | None = None
    metal: Metal = Field(default_factory=Metal)
    center_stone: Stone = Field(default_factory=Stone)
    side_stones: tuple[SideStoneGroup, ...] = ()
    construction: Construction = Field(default_factory=Construction)
    style: State[tuple[DomainId, ...]] | None = None
    references: State[tuple[AssetReference, ...]] | None = None
    visual_constraints: State[tuple[VisualConstraint, ...]] | None = None

    @model_validator(mode="after")
    def unique_groups(self):
        ids = [group.group_id for group in self.side_stones]
        if len(set(ids)) != len(ids):
            raise ValueError("Side stone group IDs must be unique")
        return self


class RevisionEvent(ImmutableModel):
    action: Literal["create", "edit", "confirm", "lock", "unlock"]
    source: MessageSource
    reason: Text


class DesignRevision(ImmutableModel):
    schema_version: Literal["1.0.0"]
    design_id: UUID
    revision_id: UUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    parent_revision_id: UUID | None = None
    created_at: AwareDatetime
    event: RevisionEvent
    design: Design

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


def snapshot_json(revision: DesignRevision) -> str:
    """Revalidate trusted Python objects too; never use model_copy for state updates."""
    return DesignRevision.model_validate(revision).model_dump_json(indent=2)
