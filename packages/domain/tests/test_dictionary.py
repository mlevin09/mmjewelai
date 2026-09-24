import inspect
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_domain import (
    AmbiguousMatch,
    DictionaryCategory,
    ResolvedMatch,
    UnsupportedMatch,
    load_domain_dictionary,
)
from jewelai_domain.dictionary import DictionaryBundle, DictionaryRegistry
from jewelai_domain.dictionary_schema import dictionary_json_schema
from jewelai_domain.roles import RoleId

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "dictionary" / "v1.0.0.json"
SCHEMA = ROOT / "specs" / "dictionary" / "schema.json"


@pytest.fixture
def catalog_data():
    return json.loads(CATALOG.read_text())


@pytest.fixture
def registry():
    return load_domain_dictionary(CATALOG)


def entry(data, domain_id):
    return next(item for item in data["entries"] if item["domain_id"] == domain_id)


def test_committed_schema_matches_generator_and_validates_catalog(catalog_data):
    generated = dictionary_json_schema()
    assert json.loads(SCHEMA.read_text()) == generated
    Draft202012Validator.check_schema(generated)
    Draft202012Validator(generated).validate(catalog_data)
    DictionaryBundle.model_validate(catalog_data)


def test_catalog_loads_with_stable_version_and_ids(registry):
    assert registry.artifact_version == "1.0.0"
    assert len(registry) == 21
    assert registry["emerald"].domain_id == "emerald"


def test_seed_covers_every_required_schema_category(registry):
    populated = {item.category for item in registry.values()}
    assert populated == set(DictionaryCategory)
    assert {
        DictionaryCategory.GEMSTONE_MATERIAL,
        DictionaryCategory.STONE_SHAPE,
        DictionaryCategory.STONE_CUT,
        DictionaryCategory.STONE_SETTING,
        DictionaryCategory.METAL_MATERIAL,
        DictionaryCategory.METAL_COLOR,
        DictionaryCategory.METAL_PURITY,
        DictionaryCategory.CONSTRUCTION,
        DictionaryCategory.STYLE,
    } <= populated


@pytest.mark.parametrize(
    ("term", "locale", "category", "domain_id", "matched_via"),
    [
        ("emerald", "en", "gemstone_material", "emerald", "canonical"),
        ("  EMERALD   GEMSTONE ", "en-US", "gemstone_material", "emerald", "synonym"),
        ("изумруд", "ru", "gemstone_material", "emerald", "canonical"),
        ("крапан", "ru-RU", "stone_setting", "prong_setting", "synonym"),
        ("ROSE GOLD", "en", "metal_color", "rose", "synonym"),
    ],
)
def test_canonical_synonym_and_locale_lookup(
    registry, term, locale, category, domain_id, matched_via
):
    result = registry.normalize(term, locale=locale, category=category)
    assert isinstance(result, ResolvedMatch)
    assert result.candidate.domain_id == domain_id
    assert result.candidate.matched_via.value == matched_via


def test_repeated_lookup_is_deterministic(registry):
    first = registry.normalize("  Emerald  ", locale="EN", category="gemstone_material")
    assert all(
        registry.normalize("  Emerald  ", locale="EN", category="gemstone_material") == first
        for _ in range(10)
    )


def test_emerald_material_and_emerald_cut_are_distinct(registry):
    material = registry.normalize("emerald", locale="en", category="gemstone_material")
    shape = registry.normalize("emerald cut", locale="en", category="stone_shape")
    assert isinstance(material, ResolvedMatch)
    assert isinstance(shape, ResolvedMatch)
    assert material.candidate.domain_id == "emerald"
    assert shape.candidate.domain_id == "emerald_cut"
    assert material.candidate.category != shape.candidate.category


def test_cross_category_term_is_ambiguous_without_context(registry):
    result = registry.normalize("halo", locale="en")
    assert isinstance(result, AmbiguousMatch)
    assert [(candidate.category.value, candidate.domain_id) for candidate in result.candidates] == [
        ("stone_setting", "halo_setting"),
        ("style", "halo_style"),
    ]


@pytest.mark.parametrize(
    ("category", "domain_id"),
    [("stone_setting", "halo_setting"), ("style", "halo_style")],
)
def test_category_context_resolves_cross_category_term(registry, category, domain_id):
    result = registry.normalize("halo", locale="en", category=category)
    assert isinstance(result, ResolvedMatch)
    assert result.candidate.domain_id == domain_id


def test_russian_cross_category_term_is_also_ambiguous(registry):
    result = registry.normalize("гало", locale="ru-RU")
    assert isinstance(result, AmbiguousMatch)
    assert {candidate.domain_id for candidate in result.candidates} == {
        "halo_setting",
        "halo_style",
    }


def test_deprecated_alias_is_visible_to_caller(registry):
    result = registry.normalize("emerald shape", locale="en", category="stone_shape")
    assert isinstance(result, ResolvedMatch)
    assert result.candidate.domain_id == "emerald_cut"
    assert result.candidate.matched_via.value == "deprecated_alias"
    assert result.candidate.deprecated_input
    assert not result.candidate.entry_deprecated


def test_deprecated_entry_exposes_same_category_replacement(catalog_data):
    item = entry(catalog_data, "halo_style")
    item["lifecycle"] = "deprecated"
    item["replaced_by"] = "minimalist"
    registry = DictionaryRegistry(DictionaryBundle.model_validate(catalog_data))
    result = registry.normalize("halo style", locale="en", category="style")
    assert isinstance(result, ResolvedMatch)
    assert result.candidate.entry_deprecated
    assert result.candidate.replaced_by == "minimalist"


def test_unsupported_locale_is_a_typed_outcome(registry):
    result = registry.normalize("emerald", locale="fr-CA")
    assert isinstance(result, UnsupportedMatch)
    assert result.reason == "unsupported_locale"
    assert result.locale is None


def test_unsupported_term_and_wrong_category_are_distinct(registry):
    missing = registry.normalize("not a catalog term", locale="en")
    wrong_category = registry.normalize("emerald", locale="en", category="style")
    assert isinstance(missing, UnsupportedMatch) and missing.reason == "term_not_found"
    assert isinstance(wrong_category, UnsupportedMatch)
    assert wrong_category.reason == "category_no_match"


def test_invalid_runtime_category_is_rejected(registry):
    with pytest.raises(ValueError):
        registry.normalize("emerald", locale="en", category="authorization_role")


def test_duplicate_stable_ids_are_rejected(catalog_data):
    catalog_data["entries"][1]["domain_id"] = catalog_data["entries"][0]["domain_id"]
    with pytest.raises(ValidationError, match="domain IDs must be unique"):
        DictionaryBundle.model_validate(catalog_data)


@pytest.mark.parametrize("bad_id", ["Emerald", "emerald-cut", "3stone", ""])
def test_malformed_domain_ids_are_rejected(catalog_data, bad_id):
    catalog_data["entries"][0]["domain_id"] = bad_id
    with pytest.raises(ValidationError):
        DictionaryBundle.model_validate(catalog_data)


def test_invalid_category_is_rejected(catalog_data):
    catalog_data["entries"][0]["category"] = "authorization"
    with pytest.raises(ValidationError):
        DictionaryBundle.model_validate(catalog_data)


def test_conflicting_term_within_category_is_rejected(catalog_data):
    entry(catalog_data, "oval")["synonyms"]["en"].append("emerald cut")
    with pytest.raises(ValidationError, match="Conflicting dictionary term"):
        DictionaryBundle.model_validate(catalog_data)


def test_duplicate_alias_within_entry_is_rejected(catalog_data):
    entry(catalog_data, "oval")["synonyms"]["en"].append("OVAL")
    with pytest.raises(ValidationError, match="duplicate terms"):
        DictionaryBundle.model_validate(catalog_data)


def test_cross_category_collision_is_valid_and_explicit(catalog_data):
    bundle = DictionaryBundle.model_validate(catalog_data)
    result = DictionaryRegistry(bundle).normalize("halo", locale="en")
    assert isinstance(result, AmbiguousMatch)


@pytest.mark.parametrize("version", ["2.0.0", "1", "v1.0.0", ""])
def test_invalid_dictionary_schema_version_is_rejected(catalog_data, version):
    catalog_data["schema_version"] = version
    with pytest.raises(ValidationError):
        DictionaryBundle.model_validate(catalog_data)


def test_artifact_version_must_be_semantic(catalog_data):
    catalog_data["artifact_version"] = "latest"
    with pytest.raises(ValidationError):
        DictionaryBundle.model_validate(catalog_data)


def test_inconsistent_deprecation_metadata_is_rejected(catalog_data):
    item = entry(catalog_data, "minimalist")
    item["lifecycle"] = "deprecated"
    with pytest.raises(ValidationError, match="must name its replacement"):
        DictionaryBundle.model_validate(catalog_data)


def test_unknown_deprecation_replacement_is_rejected(catalog_data):
    item = entry(catalog_data, "minimalist")
    item["lifecycle"] = "deprecated"
    item["replaced_by"] = "unknown_style"
    with pytest.raises(ValidationError, match="Unknown replacement ID"):
        DictionaryBundle.model_validate(catalog_data)


@pytest.mark.parametrize(
    ("field", "value"),
    [("review_status", "approved_by_ai"), ("source_ref", "")],
)
def test_invalid_provenance_is_rejected(catalog_data, field, value):
    entry(catalog_data, "emerald")["provenance"][field] = value
    with pytest.raises(ValidationError):
        DictionaryBundle.model_validate(catalog_data)


def test_dictionary_contains_no_gemstone_measurement_facts(catalog_data):
    forbidden_keys = {"dimensions", "weight", "density", "tolerance", "measurement"}

    def nested_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from nested_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from nested_keys(child)

    assert forbidden_keys.isdisjoint(nested_keys(catalog_data))
    for item in catalog_data["entries"]:
        serialized = json.dumps(item, ensure_ascii=False)
        assert not re.search(r"\b\d+(?:\.\d+)?\s*(?:ct|carat|mm)\b", serialized, re.IGNORECASE)


def test_dictionary_does_not_parse_or_derive_dimensions(registry):
    result = registry.normalize("3 ct emerald", locale="en", category="gemstone_material")
    assert isinstance(result, UnsupportedMatch)
    assert result.reason == "category_no_match"
    assert not hasattr(result, "dimensions")


def test_all_roles_share_one_role_independent_dictionary_interface(registry):
    assert "role" not in inspect.signature(DictionaryRegistry.normalize).parameters
    expected = registry.normalize("emerald", locale="en", category="gemstone_material")
    assert all(
        registry.normalize("emerald", locale="en", category="gemstone_material") == expected
        for _role in RoleId
    )
