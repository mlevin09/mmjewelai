"""Opt-in F04 question contract. The frozen five-question V1 vocabulary is unchanged."""

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .dictionary import DictionaryCategory
from .questions import (
    _QUESTION_CONTRACT,
    DictionaryAnswerContract,
    QuestionCatalog,
    QuestionCatalogBundle,
    QuestionEntry,
    QuestionLocale,
    RenderedQuestion,
    _validate_schema_target,
)


class QuestionIdV2(StrEnum):
    CENTER_STONE_SHAPE = "CENTER_STONE_SHAPE"
    CENTER_STONE_DIMENSIONS = "CENTER_STONE_DIMENSIONS"
    CENTER_STONE_SETTING = "CENTER_STONE_SETTING"
    METAL_COLOR = "METAL_COLOR"
    SIDE_STONE_QUANTITY = "SIDE_STONE_QUANTITY"
    METAL_MATERIAL = "METAL_MATERIAL"


class SchemaTargetV2(StrEnum):
    CENTER_STONE_SHAPE = "center_stone.shape"
    CENTER_STONE_DIMENSIONS = "center_stone.dimensions"
    CENTER_STONE_SETTING = "center_stone.setting"
    METAL_COLOR = "metal.color"
    SIDE_STONE_QUANTITY = "side_stones[*].quantity"
    METAL_MATERIAL = "metal.material"


class QuestionEntryV2(QuestionEntry):
    question_id: QuestionIdV2
    target: SchemaTargetV2


class QuestionCatalogBundleV2(QuestionCatalogBundle):
    schema_version: Literal["2.0.0"]
    artifact_version: Literal["2.0.0"]
    entries: tuple[QuestionEntryV2, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_catalog(self):
        if self.supported_locales != tuple(QuestionLocale):
            raise ValueError("F04 requires both exact catalog locales")
        if tuple(e.question_id for e in self.entries) != tuple(QuestionIdV2):
            raise ValueError("F04 requires its six semantic IDs in canonical order")
        for entry in self.entries:
            if entry.question_id == QuestionIdV2.METAL_MATERIAL:
                if (
                    entry.target != SchemaTargetV2.METAL_MATERIAL
                    or not isinstance(entry.answer_contract, DictionaryAnswerContract)
                    or entry.answer_contract.dictionary_category
                    != DictionaryCategory.METAL_MATERIAL
                ):
                    raise ValueError("F04 material question must use the material Dictionary")
            else:
                _validate_schema_target(entry.target)
                target, kind, category = _QUESTION_CONTRACT[entry.question_id]
                if (
                    entry.target != target
                    or entry.answer_contract.kind != kind
                    or getattr(entry.answer_contract, "dictionary_category", None) != category
                ):
                    raise ValueError("F04 cannot reinterpret an existing question")
        return self


class RenderedQuestionV2(RenderedQuestion):
    question_id: QuestionIdV2
    target: SchemaTargetV2


class QuestionCatalogV2(QuestionCatalog):
    """Reuse catalog cross-validation and deterministic role rendering."""

    _bundle_type = QuestionCatalogBundleV2
    _question_id_type = QuestionIdV2
    _rendered_type = RenderedQuestionV2
