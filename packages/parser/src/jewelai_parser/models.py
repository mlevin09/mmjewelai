"""Versioned immutable contracts for untrusted candidates and deterministic proposals."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain import Design
from jewelai_domain.dictionary import MatchCandidate, MatchKind
from jewelai_domain.models import (
    Dimensions,
    DomainId,
    FinenessPurity,
    ImmutableModel,
    KaratPurity,
    MessageSource,
    StoneQuantity,
    Text,
    Weight,
)
from pydantic import Field, StringConstraints, field_validator, model_validator

PARSER_SCHEMA_VERSION = "1.0.0"
CandidateText = Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]


class ParserTarget(StrEnum):
    JEWELRY_TYPE = "jewelry_type"
    METAL_MATERIAL = "metal.material"
    METAL_COLOR = "metal.color"
    METAL_PURITY = "metal.purity"
    CENTER_STONE_MATERIAL = "center_stone.material"
    CENTER_STONE_SHAPE = "center_stone.shape"
    CENTER_STONE_CUT = "center_stone.cut"
    CENTER_STONE_WEIGHT = "center_stone.weight"
    CENTER_STONE_DIMENSIONS = "center_stone.dimensions"
    CENTER_STONE_SETTING = "center_stone.setting"
    STYLE = "style"
    SIDE_STONE_QUANTITY = "side_stones[*].quantity"


class TermCandidate(ImmutableModel):
    kind: Literal["term"] = "term"
    text: CandidateText


class WeightCandidate(ImmutableModel):
    kind: Literal["weight"] = "weight"
    value: Weight


class DimensionsCandidate(ImmutableModel):
    kind: Literal["dimensions"] = "dimensions"
    value: Dimensions


class PurityCandidate(ImmutableModel):
    kind: Literal["purity"] = "purity"
    value: KaratPurity | FinenessPurity


class QuantityCandidate(ImmutableModel):
    kind: Literal["quantity"] = "quantity"
    value: StoneQuantity


class StyleTermsCandidate(ImmutableModel):
    kind: Literal["style_terms"] = "style_terms"
    terms: Annotated[tuple[CandidateText, ...], Field(min_length=1)]

    @field_validator("terms")
    @classmethod
    def stable_term_order(cls, value):
        return tuple(sorted(value, key=lambda item: item.casefold()))


CandidateValue = Annotated[
    TermCandidate
    | WeightCandidate
    | DimensionsCandidate
    | PurityCandidate
    | QuantityCandidate
    | StyleTermsCandidate,
    Field(discriminator="kind"),
]


_TERM_TARGETS = {
    ParserTarget.JEWELRY_TYPE,
    ParserTarget.METAL_MATERIAL,
    ParserTarget.METAL_COLOR,
    ParserTarget.CENTER_STONE_MATERIAL,
    ParserTarget.CENTER_STONE_SHAPE,
    ParserTarget.CENTER_STONE_CUT,
    ParserTarget.CENTER_STONE_SETTING,
}


class CandidateUpdate(ImmutableModel):
    target: ParserTarget
    value: CandidateValue
    group_id: DomainId | None = None

    @property
    def concrete_target(self) -> str:
        if self.target == ParserTarget.SIDE_STONE_QUANTITY:
            return f"side_stones.{self.group_id}.quantity"
        return self.target.value

    @model_validator(mode="after")
    def validate_target_value(self):
        expected = {
            ParserTarget.METAL_PURITY: PurityCandidate,
            ParserTarget.CENTER_STONE_WEIGHT: WeightCandidate,
            ParserTarget.CENTER_STONE_DIMENSIONS: DimensionsCandidate,
            ParserTarget.STYLE: StyleTermsCandidate,
            ParserTarget.SIDE_STONE_QUANTITY: QuantityCandidate,
        }
        if self.target in _TERM_TARGETS and not isinstance(self.value, TermCandidate):
            raise ValueError(f"{self.target.value} requires a term candidate")
        required = expected.get(self.target)
        if required is not None and not isinstance(self.value, required):
            raise ValueError(f"{self.target.value} has an incompatible candidate kind")
        if (self.target == ParserTarget.SIDE_STONE_QUANTITY) != (self.group_id is not None):
            raise ValueError("Only side-stone quantity requires a stable group_id")
        return self


class ParserCandidate(ImmutableModel):
    schema_version: Literal["1.0.0"] = PARSER_SCHEMA_VERSION
    updates: tuple[CandidateUpdate, ...] = ()

    @model_validator(mode="after")
    def reject_duplicates(self):
        targets = [update.concrete_target for update in self.updates]
        if len(set(targets)) != len(targets):
            raise ValueError("Parser candidate contains duplicate concrete targets")
        return self


class ParserIssueCode(StrEnum):
    AMBIGUOUS_TERM = "AMBIGUOUS_TERM"
    UNSUPPORTED_TERM = "UNSUPPORTED_TERM"
    DEPRECATED_ENTRY = "DEPRECATED_ENTRY"
    LOCKED_FIELD_CONFLICT = "LOCKED_FIELD_CONFLICT"
    UNKNOWN_SIDE_STONE_GROUP = "UNKNOWN_SIDE_STONE_GROUP"


class ParserWarningCode(StrEnum):
    DEPRECATED_ALIAS_USED = "DEPRECATED_ALIAS_USED"


class ParserIssue(ImmutableModel):
    code: ParserIssueCode
    target: ParserTarget
    concrete_target: Text
    normalized_input: str | None = None
    candidates: tuple[MatchCandidate, ...] = ()
    detail: Text


class ParserWarning(ImmutableModel):
    code: ParserWarningCode
    target: ParserTarget
    concrete_target: Text
    normalized_input: str
    canonical_id: DomainId


CanonicalValue = (
    DomainId
    | Weight
    | Dimensions
    | KaratPurity
    | FinenessPurity
    | StoneQuantity
    | tuple[DomainId, ...]
)


class AcceptedUpdate(ImmutableModel):
    target: ParserTarget
    concrete_target: Text
    candidate_value: CandidateValue
    canonical_value: CanonicalValue
    match_kind: MatchKind | None = None


class ParserProposal(ImmutableModel):
    schema_version: Literal["1.0.0"] = PARSER_SCHEMA_VERSION
    expected_revision_id: UUID
    source: MessageSource
    locale: Literal["en", "ru"]
    dictionary_artifact_version: str
    proposed_design: Design
    accepted_updates: tuple[AcceptedUpdate, ...] = ()
    issues: tuple[ParserIssue, ...] = ()
    warnings: tuple[ParserWarning, ...] = ()
    has_changes: bool

    @model_validator(mode="after")
    def validate_change_flag(self):
        if self.has_changes != bool(self.accepted_updates):
            raise ValueError("has_changes must match accepted updates")
        return self
