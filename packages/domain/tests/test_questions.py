import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_domain import (
    QuestionId,
    RoleId,
    SchemaTarget,
    UnknownQuestionError,
    UnknownRoleError,
    UnsupportedLocaleError,
    load_domain_dictionary,
    load_question_catalog,
    load_role_profiles,
)
from jewelai_domain.dictionary import DictionaryCategory
from jewelai_domain.models import Design, Metal, SideStoneGroup, Stone
from jewelai_domain.questions import QuestionCatalog, QuestionCatalogBundle
from jewelai_domain.questions_schema import question_catalog_json_schema

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "questions" / "v1.0.0.json"
SCHEMA = ROOT / "specs" / "questions" / "schema.json"
ROLES = ROOT / "data" / "roles" / "v1.0.0.json"
DICTIONARY = ROOT / "data" / "dictionary" / "v1.0.0.json"


@pytest.fixture
def catalog_data():
    return json.loads(CATALOG.read_text())


@pytest.fixture
def roles():
    return load_role_profiles(ROLES)


@pytest.fixture
def dictionary():
    return load_domain_dictionary(DICTIONARY)


@pytest.fixture
def catalog(roles, dictionary):
    return load_question_catalog(CATALOG, roles=roles, dictionary=dictionary)


def question(data, question_id):
    return next(item for item in data["entries"] if item["question_id"] == question_id)


def build_catalog(data, roles, dictionary):
    return QuestionCatalog(
        QuestionCatalogBundle.model_validate(data), roles=roles, dictionary=dictionary
    )


def test_committed_schema_matches_generator_and_validates_catalog(catalog_data):
    generated = question_catalog_json_schema()
    assert json.loads(SCHEMA.read_text()) == generated
    Draft202012Validator.check_schema(generated)
    Draft202012Validator(generated).validate(catalog_data)
    QuestionCatalogBundle.model_validate(catalog_data)


def test_catalog_loads_with_stable_versions_and_expected_ids(catalog):
    assert catalog.artifact_version == "1.0.0"
    assert tuple(catalog) == tuple(QuestionId)
    assert len(catalog) == 5


def test_bundle_pins_schema_role_and_dictionary_versions(catalog_data):
    bundle = QuestionCatalogBundle.model_validate(catalog_data)
    assert bundle.schema_version == "1.0.0"
    assert bundle.design_schema_version == "1.0.0"
    assert bundle.role_artifact_version == "1.0.0"
    assert bundle.dictionary_artifact_version == "1.0.0"


def test_canonical_targets_exist_in_actual_schema_models(catalog):
    assert "center_stone" in Design.model_fields
    assert {"shape", "dimensions", "setting"} <= Stone.model_fields.keys()
    assert "metal" in Design.model_fields and "color" in Metal.model_fields
    assert "side_stones" in Design.model_fields and "quantity" in SideStoneGroup.model_fields
    assert {entry.target for entry in catalog.values()} == set(SchemaTarget)


def test_answer_contracts_use_schema_types_and_dictionary_categories(catalog):
    expected = {
        QuestionId.CENTER_STONE_SHAPE: ("dictionary_id", "DomainId", "stone_shape"),
        QuestionId.CENTER_STONE_DIMENSIONS: ("dimensions", "Dimensions", None),
        QuestionId.CENTER_STONE_SETTING: ("dictionary_id", "DomainId", "stone_setting"),
        QuestionId.METAL_COLOR: ("dictionary_id", "DomainId", "metal_color"),
        QuestionId.SIDE_STONE_QUANTITY: ("stone_quantity", "StoneQuantity", None),
    }
    for question_id, (kind, schema_type, category) in expected.items():
        contract = catalog[question_id].answer_contract
        assert contract.kind == kind
        assert contract.schema_type == schema_type
        assert getattr(contract, "dictionary_category", None) == category


@pytest.mark.parametrize("role_id", RoleId)
@pytest.mark.parametrize("locale", ["en", "ru"])
def test_every_role_and_locale_renders_deterministically(catalog, role_id, locale):
    first = catalog.render(QuestionId.CENTER_STONE_SHAPE, role_id, locale)
    assert all(
        catalog.render(QuestionId.CENTER_STONE_SHAPE, role_id, locale) == first for _ in range(5)
    )
    assert first.role_id == role_id
    assert first.locale.value == locale
    assert first.wording


def test_retail_wording_is_consumer_friendly_and_industrial_wording_is_technical(catalog):
    retail = catalog.render("CENTER_STONE_SHAPE", "retail_client", "en")
    industrial = catalog.render("CENTER_STONE_SHAPE", "industrial_designer", "en")
    assert retail.wording == "What shape would you like for the center stone?"
    assert "canonical" in industrial.wording and "identifier" in industrial.wording


@pytest.mark.parametrize(
    ("requested", "resolved"), [("en-US", "en"), ("EN_gb", "en"), ("ru-RU", "ru")]
)
def test_regional_locale_uses_role_profile_base_language_fallback(catalog, requested, resolved):
    rendered = catalog.render("METAL_COLOR", "sales_manager", requested)
    assert rendered.locale.value == resolved


def test_unsupported_locale_and_unknown_role_are_typed_errors(catalog):
    with pytest.raises(UnsupportedLocaleError):
        catalog.render("METAL_COLOR", "retail_client", "fr-CA")
    with pytest.raises(UnknownRoleError):
        catalog.render("METAL_COLOR", "administrator", "en")


def test_unknown_question_is_a_typed_error(catalog):
    with pytest.raises(UnknownQuestionError):
        catalog.render("NEXT_BEST_QUESTION", "retail_client", "en")


@pytest.mark.parametrize("question_id", QuestionId)
def test_role_and_locale_only_change_presentation(catalog, question_id):
    baseline = catalog.render(question_id, RoleId.RETAIL_CLIENT, "en")
    for role_id in RoleId:
        for locale in ("en", "ru"):
            rendered = catalog.render(question_id, role_id, locale)
            assert rendered.question_id == baseline.question_id
            assert rendered.target == baseline.target
            assert rendered.answer_contract == baseline.answer_contract
            assert rendered.artifact_version == baseline.artifact_version


def test_side_stone_target_is_generic_and_not_a_fixture_group(catalog):
    target = catalog[QuestionId.SIDE_STONE_QUANTITY].target.value
    assert target == "side_stones[*].quantity"
    assert "group_" not in target


def test_duplicate_semantic_ids_are_rejected(catalog_data):
    catalog_data["entries"][1]["question_id"] = catalog_data["entries"][0]["question_id"]
    with pytest.raises(ValidationError, match="IDs must be unique"):
        QuestionCatalogBundle.model_validate(catalog_data)


@pytest.mark.parametrize("bad_id", ["center_stone_shape", "CENTER-STONE-SHAPE", "", "OTHER"])
def test_malformed_or_unknown_semantic_ids_are_rejected(catalog_data, bad_id):
    catalog_data["entries"][0]["question_id"] = bad_id
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


@pytest.mark.parametrize(
    "bad_target", ["center_stone.unknown", "side_stones[group_1].quantity", "metal.material"]
)
def test_invalid_or_unbounded_schema_targets_are_rejected(catalog_data, bad_target):
    question(catalog_data, "CENTER_STONE_SHAPE")["target"] = bad_target
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_target_and_answer_contract_mismatch_is_rejected(catalog_data):
    item = question(catalog_data, "CENTER_STONE_DIMENSIONS")
    item["answer_contract"] = {
        "kind": "stone_quantity",
        "schema_type": "StoneQuantity",
        "value": "positive_integer",
        "scopes": ["per_side", "per_item", "per_pair"],
    }
    with pytest.raises(ValidationError, match="incompatible target or answer contract"):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_wrong_dictionary_category_is_rejected(catalog_data):
    item = question(catalog_data, "CENTER_STONE_SHAPE")
    item["answer_contract"]["dictionary_category"] = "metal_color"
    with pytest.raises(ValidationError, match="incompatible target or answer contract"):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_invalid_dictionary_category_is_rejected(catalog_data):
    item = question(catalog_data, "CENTER_STONE_SHAPE")
    item["answer_contract"]["dictionary_category"] = "authorization"
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_unknown_dictionary_example_is_rejected(catalog_data, roles, dictionary):
    item = question(catalog_data, "CENTER_STONE_SHAPE")
    item["examples"][0]["dictionary_id"] = "not_in_dictionary"
    with pytest.raises(ValueError, match="Unknown dictionary example ID"):
        build_catalog(catalog_data, roles, dictionary)


def test_dictionary_example_with_wrong_category_is_rejected(catalog_data, roles, dictionary):
    item = question(catalog_data, "CENTER_STONE_SHAPE")
    item["examples"][0]["dictionary_id"] = "white"
    with pytest.raises(ValueError, match="wrong category"):
        build_catalog(catalog_data, roles, dictionary)


def test_non_dictionary_contract_cannot_smuggle_dictionary_example(catalog_data):
    item = question(catalog_data, "CENTER_STONE_DIMENSIONS")
    item["examples"][0]["dictionary_id"] = "oval"
    with pytest.raises(ValidationError, match="Only dictionary-backed questions"):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_duplicate_role_wording_is_rejected(catalog_data):
    wordings = question(catalog_data, "METAL_COLOR")["wording"]
    wordings[-1] = deepcopy(wordings[0])
    with pytest.raises(ValidationError, match="variants must be unique"):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_invalid_role_reference_is_rejected(catalog_data):
    wording = question(catalog_data, "METAL_COLOR")["wording"][0]
    wording["role_id"] = "administrator"
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


@pytest.mark.parametrize("missing_locale", ["en", "ru"])
def test_missing_translation_is_rejected(catalog_data, missing_locale):
    text = question(catalog_data, "METAL_COLOR")["wording"][0]["text"]
    del text[missing_locale]
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_extra_locale_variant_is_rejected(catalog_data):
    text = question(catalog_data, "METAL_COLOR")["wording"][0]["text"]
    text["fr"] = "Quelle couleur?"
    with pytest.raises(ValidationError, match="Extra inputs"):
        QuestionCatalogBundle.model_validate(catalog_data)


@pytest.mark.parametrize("version", ["latest", "1", "v1.0.0", ""])
def test_malformed_artifact_version_is_rejected(catalog_data, version):
    catalog_data["artifact_version"] = version
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_invalid_provenance_or_review_state_is_rejected(catalog_data):
    item = question(catalog_data, "CENTER_STONE_SETTING")
    item["provenance"]["review_status"] = "production_approved"
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(catalog_data)


def test_pinned_role_and_dictionary_versions_must_match(catalog_data, roles, dictionary):
    catalog_data["role_artifact_version"] = "1.0.1"
    with pytest.raises(ValueError, match="role artifact version"):
        build_catalog(catalog_data, roles, dictionary)
    catalog_data["role_artifact_version"] = "1.0.0"
    catalog_data["dictionary_artifact_version"] = "1.0.1"
    with pytest.raises(ValueError, match="dictionary artifact version"):
        build_catalog(catalog_data, roles, dictionary)


def test_catalog_contract_rejects_question_selection_fields(catalog_data):
    item = question(catalog_data, "CENTER_STONE_SHAPE")
    for forbidden in ("condition", "priority", "required", "next_question", "readiness"):
        mutated = deepcopy(catalog_data)
        question(mutated, item["question_id"])[forbidden] = True
        with pytest.raises(ValidationError, match="Extra inputs"):
            QuestionCatalogBundle.model_validate(mutated)


def test_artifact_contains_no_selection_or_rules_engine_keys(catalog_data):
    forbidden = {
        "condition",
        "priority",
        "required",
        "next_question",
        "readiness",
        "derive",
        "assume",
        "block",
        "max_questions",
    }

    def keys(value):
        if isinstance(value, dict):
            yield from value
            for child in value.values():
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert forbidden.isdisjoint(keys(catalog_data))
    assert "design" not in inspect.signature(QuestionCatalog.render).parameters


def test_examples_do_not_encode_gemstone_dimension_facts(catalog_data):
    dimensions = question(catalog_data, "CENTER_STONE_DIMENSIONS")
    serialized = json.dumps(dimensions["examples"], ensure_ascii=False)
    assert not any(character.isdigit() for character in serialized)
    assert "carat" not in serialized.casefold()


def test_dictionary_backed_questions_use_required_categories(catalog):
    assert (
        catalog[QuestionId.CENTER_STONE_SHAPE].answer_contract.dictionary_category
        == DictionaryCategory.STONE_SHAPE
    )
    assert (
        catalog[QuestionId.CENTER_STONE_SETTING].answer_contract.dictionary_category
        == DictionaryCategory.STONE_SETTING
    )
    assert (
        catalog[QuestionId.METAL_COLOR].answer_contract.dictionary_category
        == DictionaryCategory.METAL_COLOR
    )
