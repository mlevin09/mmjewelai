"""Versioned semantic questions and deterministic role/locale rendering."""

import json
from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .dictionary import DictionaryCategory, DictionaryRegistry, ReviewStatus
from .models import (
    SCHEMA_VERSION,
    Design,
    DomainId,
    ImmutableModel,
    Metal,
    SideStoneGroup,
    Stone,
    Text,
    Version,
)
from .roles import RoleId, RoleRegistry

QUESTION_SCHEMA_VERSION = "1.0.0"


class QuestionId(StrEnum):
    CENTER_STONE_SHAPE = "CENTER_STONE_SHAPE"
    CENTER_STONE_DIMENSIONS = "CENTER_STONE_DIMENSIONS"
    CENTER_STONE_SETTING = "CENTER_STONE_SETTING"
    METAL_COLOR = "METAL_COLOR"
    SIDE_STONE_QUANTITY = "SIDE_STONE_QUANTITY"


class QuestionLocale(StrEnum):
    EN = "en"
    RU = "ru"


class SchemaTarget(StrEnum):
    """The complete bounded target vocabulary for Question Catalog v1."""

    CENTER_STONE_SHAPE = "center_stone.shape"
    CENTER_STONE_DIMENSIONS = "center_stone.dimensions"
    CENTER_STONE_SETTING = "center_stone.setting"
    METAL_COLOR = "metal.color"
    SIDE_STONE_QUANTITY = "side_stones[*].quantity"


class DictionaryAnswerContract(ImmutableModel):
    kind: Literal["dictionary_id"] = "dictionary_id"
    schema_type: Literal["DomainId"] = "DomainId"
    dictionary_category: DictionaryCategory


class DimensionsAnswerContract(ImmutableModel):
    kind: Literal["dimensions"] = "dimensions"
    schema_type: Literal["Dimensions"] = "Dimensions"
    unit: Literal["mm"] = "mm"
    components: tuple[Literal["length", "width", "depth"], ...] = (
        "length",
        "width",
        "depth",
    )

    @model_validator(mode="after")
    def validate_components(self):
        if self.components != ("length", "width", "depth"):
            raise ValueError("Dimensions must use the canonical length, width, depth components")
        return self


class StoneQuantityAnswerContract(ImmutableModel):
    kind: Literal["stone_quantity"] = "stone_quantity"
    schema_type: Literal["StoneQuantity"] = "StoneQuantity"
    value: Literal["positive_integer"] = "positive_integer"
    scopes: tuple[Literal["per_side", "per_item", "per_pair"], ...] = (
        "per_side",
        "per_item",
        "per_pair",
    )

    @model_validator(mode="after")
    def validate_scopes(self):
        if self.scopes != ("per_side", "per_item", "per_pair"):
            raise ValueError("StoneQuantity must expose all canonical scopes in stable order")
        return self


AnswerContract = Annotated[
    DictionaryAnswerContract | DimensionsAnswerContract | StoneQuantityAnswerContract,
    Field(discriminator="kind"),
]


class LocalizedQuestionText(ImmutableModel):
    en: Text
    ru: Text

    def for_locale(self, locale: QuestionLocale) -> str:
        return getattr(self, locale.value)


class RoleWording(ImmutableModel):
    role_id: RoleId
    text: LocalizedQuestionText


class QuestionExample(ImmutableModel):
    description: LocalizedQuestionText
    dictionary_id: DomainId | None = None


class QuestionProvenance(ImmutableModel):
    source_kind: Literal["repository_spec"] = "repository_spec"
    source_ref: Literal["docs/product/issues/04-questions.md"]
    review_status: ReviewStatus


class QuestionEntry(ImmutableModel):
    question_id: QuestionId
    target: SchemaTarget
    answer_contract: AnswerContract
    wording: tuple[RoleWording, ...] = Field(min_length=6, max_length=6)
    examples: tuple[QuestionExample, ...] = Field(min_length=1)
    provenance: QuestionProvenance

    @model_validator(mode="after")
    def validate_entry(self):
        role_ids = tuple(item.role_id for item in self.wording)
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("Role wording variants must be unique")
        if role_ids != tuple(RoleId):
            raise ValueError("Every question must provide all six roles in canonical order")

        uses_dictionary = isinstance(self.answer_contract, DictionaryAnswerContract)
        for example in self.examples:
            if uses_dictionary != (example.dictionary_id is not None):
                raise ValueError(
                    "Only dictionary-backed questions may use dictionary ID examples, and each "
                    "dictionary-backed example must name one"
                )
        return self


# Each target is intentionally mapped to concrete Schema v1 model fields. This is not a generic
# path evaluator: adding a target requires an explicit contract change and validation here.
_TARGET_FIELDS = {
    SchemaTarget.CENTER_STONE_SHAPE: ((Design, "center_stone"), (Stone, "shape")),
    SchemaTarget.CENTER_STONE_DIMENSIONS: ((Design, "center_stone"), (Stone, "dimensions")),
    SchemaTarget.CENTER_STONE_SETTING: ((Design, "center_stone"), (Stone, "setting")),
    SchemaTarget.METAL_COLOR: ((Design, "metal"), (Metal, "color")),
    SchemaTarget.SIDE_STONE_QUANTITY: (
        (Design, "side_stones"),
        (SideStoneGroup, "quantity"),
    ),
}

_QUESTION_CONTRACT = {
    QuestionId.CENTER_STONE_SHAPE: (
        SchemaTarget.CENTER_STONE_SHAPE,
        "dictionary_id",
        DictionaryCategory.STONE_SHAPE,
    ),
    QuestionId.CENTER_STONE_DIMENSIONS: (
        SchemaTarget.CENTER_STONE_DIMENSIONS,
        "dimensions",
        None,
    ),
    QuestionId.CENTER_STONE_SETTING: (
        SchemaTarget.CENTER_STONE_SETTING,
        "dictionary_id",
        DictionaryCategory.STONE_SETTING,
    ),
    QuestionId.METAL_COLOR: (
        SchemaTarget.METAL_COLOR,
        "dictionary_id",
        DictionaryCategory.METAL_COLOR,
    ),
    QuestionId.SIDE_STONE_QUANTITY: (
        SchemaTarget.SIDE_STONE_QUANTITY,
        "stone_quantity",
        None,
    ),
}


def _validate_schema_target(target: SchemaTarget) -> None:
    for model, field_name in _TARGET_FIELDS[target]:
        if field_name not in model.model_fields:
            raise ValueError(
                f"Question target {target.value!r} does not exist in Jewelry Design Schema v1"
            )


class QuestionCatalogBundle(ImmutableModel):
    schema_version: Literal["1.0.0"]
    artifact_version: Version
    design_schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    role_artifact_version: Version
    dictionary_artifact_version: Version
    supported_locales: tuple[QuestionLocale, ...] = (QuestionLocale.EN, QuestionLocale.RU)
    locale_fallback: Literal["base_language_then_reject"] = "base_language_then_reject"
    review_status: Literal["proposed_pending_domain_review"]
    source: Literal["docs/product/issues/04-questions.md"]
    entries: tuple[QuestionEntry, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def validate_catalog(self):
        if self.supported_locales != tuple(QuestionLocale):
            raise ValueError("Question Catalog v1 must declare en and ru in stable order")

        ids = tuple(entry.question_id for entry in self.entries)
        if len(set(ids)) != len(ids):
            raise ValueError("Semantic question IDs must be unique")
        if ids != tuple(QuestionId):
            raise ValueError("Question Catalog v1 must contain its five IDs in stable order")

        for entry in self.entries:
            _validate_schema_target(entry.target)
            target, kind, category = _QUESTION_CONTRACT[entry.question_id]
            actual_category = getattr(entry.answer_contract, "dictionary_category", None)
            if (
                entry.target != target
                or entry.answer_contract.kind != kind
                or actual_category != category
            ):
                raise ValueError(
                    f"Question {entry.question_id.value} has an incompatible target or answer "
                    "contract"
                )
        return self


class UnknownQuestionError(LookupError):
    """Raised when a caller requests a semantic ID outside Question Catalog v1."""


class RenderedQuestion(ImmutableModel):
    question_id: QuestionId
    wording: Text
    target: SchemaTarget
    answer_contract: AnswerContract
    role_id: RoleId
    locale: QuestionLocale
    artifact_version: Version


class QuestionCatalog(Mapping[QuestionId, QuestionEntry]):
    """Immutable validated catalog for rendering a selected semantic question."""

    def __init__(
        self,
        bundle: QuestionCatalogBundle,
        *,
        roles: RoleRegistry,
        dictionary: DictionaryRegistry,
    ):
        bundle = QuestionCatalogBundle.model_validate(bundle)
        if bundle.role_artifact_version != roles.artifact_version:
            raise ValueError("Question Catalog role artifact version does not match the registry")
        if bundle.dictionary_artifact_version != dictionary.artifact_version:
            raise ValueError(
                "Question Catalog dictionary artifact version does not match the registry"
            )

        for entry in bundle.entries:
            for wording in entry.wording:
                roles.get_profile(wording.role_id)
            if isinstance(entry.answer_contract, DictionaryAnswerContract):
                for example in entry.examples:
                    try:
                        dictionary_entry = dictionary[example.dictionary_id]
                    except KeyError as exc:
                        raise ValueError(
                            f"Unknown dictionary example ID: {example.dictionary_id}"
                        ) from exc
                    if dictionary_entry.category != entry.answer_contract.dictionary_category:
                        raise ValueError(
                            f"Dictionary example {example.dictionary_id} has the wrong category "
                            f"for {entry.question_id.value}"
                        )

        self._bundle = bundle
        self._roles = roles
        self._entries = MappingProxyType({entry.question_id: entry for entry in bundle.entries})

    @property
    def artifact_version(self) -> str:
        return self._bundle.artifact_version

    def __getitem__(self, question_id: QuestionId) -> QuestionEntry:
        return self._entries[question_id]

    def __iter__(self) -> Iterator[QuestionId]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def get_question(self, question_id: QuestionId | str) -> QuestionEntry:
        try:
            canonical = QuestionId(question_id)
        except ValueError as exc:
            raise UnknownQuestionError(f"Unknown semantic question: {question_id}") from exc
        return self._entries[canonical]

    def render(
        self,
        question_id: QuestionId | str,
        role_id: RoleId | str,
        locale: str,
    ) -> RenderedQuestion:
        entry = self.get_question(question_id)
        profile = self._roles.get_profile(role_id)
        resolved_locale = QuestionLocale(self._roles.resolve_locale(profile.role_id, locale))
        wording = next(item for item in entry.wording if item.role_id == profile.role_id)
        return RenderedQuestion(
            question_id=entry.question_id,
            wording=wording.text.for_locale(resolved_locale),
            target=entry.target,
            answer_contract=entry.answer_contract,
            role_id=profile.role_id,
            locale=resolved_locale,
            artifact_version=self._bundle.artifact_version,
        )


def load_question_catalog(
    path: str | Path,
    *,
    roles: RoleRegistry,
    dictionary: DictionaryRegistry,
) -> QuestionCatalog:
    """Load and cross-validate a catalog against explicit pinned registries."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return QuestionCatalog(
        QuestionCatalogBundle.model_validate(data), roles=roles, dictionary=dictionary
    )
