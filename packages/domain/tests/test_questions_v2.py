"""F04 question dispatch never broadens the frozen V1 question vocabulary."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_domain import load_domain_dictionary, load_role_profiles
from jewelai_domain.questions import QuestionCatalogBundle, QuestionId, SchemaTarget
from jewelai_domain.questions_v2 import (
    QuestionCatalogBundleV2,
    QuestionCatalogV2,
    QuestionIdV2,
    SchemaTargetV2,
)

ROOT = Path(__file__).resolve().parents[3]

APPROVED_WORDING = {
    "retail_client": (
        "Which metal would you like for the product body: {options}?",
        "Какой металл вы выбираете для основы изделия: {options}?",
    ),
    "sales_manager": (
        "Which metal should be recorded for the product body: {options}?",
        "Какой металл указать для основы изделия: {options}?",
    ),
    "buyer": (
        "Which metal is required for the product body: {options}?",
        "Какой металл требуется для основы изделия: {options}?",
    ),
    "marketing": (
        "Which metal should the product description specify for the body: {options}?",
        "Какой металл основы изделия указать в описании: {options}?",
    ),
    "jewelry_designer": (
        "Select the product-body metal: {options}.",
        "Выберите металл основы изделия: {options}.",
    ),
    "industrial_designer": (
        "Specify the material of the product body: {options}.",
        "Укажите материал основы изделия: {options}.",
    ),
}


def data():
    return json.loads((ROOT / "data/questions/v2.0.0.json").read_text())


def test_f04_schema_and_frozen_v1_dispatch():
    bundle = QuestionCatalogBundleV2.model_validate(data())
    assert len(QuestionId) == len(SchemaTarget) == 5
    assert tuple(e.question_id for e in bundle.entries) == tuple(QuestionIdV2)
    with pytest.raises(ValidationError):
        QuestionCatalogBundle.model_validate(data())
    generated = QuestionCatalogBundleV2.model_json_schema()
    assert json.loads((ROOT / "specs/questions/v2.0.0/schema.json").read_text()) == generated
    Draft202012Validator(generated).validate(data())
    old = json.loads((ROOT / "data/questions/v1.0.0.json").read_text())
    assert data()["entries"][:-1] == old["entries"]
    retained = QuestionCatalogBundle.model_validate(old)
    assert [e.model_dump(mode="json") for e in bundle.entries[:-1]] == [
        e.model_dump(mode="json") for e in retained.entries
    ]


@pytest.mark.parametrize("locale", ("en", "ru"))
def test_f04_exact_six_role_wording(locale):
    catalog = QuestionCatalogV2(
        QuestionCatalogBundleV2.model_validate(data()),
        roles=load_role_profiles(ROOT / "data/roles/v1.0.0.json"),
        dictionary=load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json"),
    )
    for role in data()["entries"][-1]["wording"]:
        actual = catalog.render("METAL_MATERIAL", role["role_id"], locale)
        assert actual.wording == role["text"][locale]
        assert actual.wording == APPROVED_WORDING[role["role_id"]][0 if locale == "en" else 1]
        assert actual.target == SchemaTargetV2.METAL_MATERIAL
        assert actual.answer_contract.dictionary_category == "metal_material"


@pytest.mark.parametrize("bad", ("metal.color", "prongs.material", "side_stones[*].material"))
def test_material_target_cannot_be_substituted(bad):
    payload = data()
    payload["entries"][-1]["target"] = bad
    with pytest.raises(ValidationError):
        QuestionCatalogBundleV2.model_validate(payload)


def test_material_answer_cannot_use_color_dictionary():
    payload = data()
    payload["entries"][-1]["answer_contract"]["dictionary_category"] = "metal_color"
    with pytest.raises(ValidationError):
        QuestionCatalogBundleV2.model_validate(payload)


def test_material_provenance_cannot_claim_the_old_five_question_spec():
    payload = data()
    payload["entries"][-1]["provenance"]["source_ref"] = "docs/product/issues/04-questions.md"
    with pytest.raises(ValidationError):
        QuestionCatalogBundleV2.model_validate(payload)
