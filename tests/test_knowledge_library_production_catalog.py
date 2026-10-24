import json
from pathlib import Path

from jewelai_domain import compile_knowledge_library
from jewelai_parser import KnowledgeLibraryMatcher, ResolvedKnowledgeMatch

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "knowledge" / "v1" / "jewelry-core-1.0.0.json"


def _runtime():
    bundle = json.loads(CATALOG.read_text(encoding="utf-8"))
    return compile_knowledge_library(bundle)


def test_production_jewelry_catalog_compiles_deterministically():
    first, first_manifest = _runtime()
    second, second_manifest = _runtime()

    assert first == second
    assert first_manifest == second_manifest
    assert first.package_id == "jewelai.production.jewelry_core"
    assert first.artifact_version == "1.0.0"
    assert first.active_for_production is False
    assert first_manifest.runtime_sha256 == first.sha256

    assert first_manifest.source_count >= 10
    assert first_manifest.claim_count >= 10
    assert first_manifest.domain_count >= 100
    assert first_manifest.language_mapping_count >= 200
    assert first_manifest.policy_count == 30


def test_production_catalog_matches_core_en_ru_terms():
    runtime, _ = _runtime()
    matcher = KnowledgeLibraryMatcher(runtime)

    cases = (
        ("diamond", "en", "diamond"),
        ("бриллиант", "ru", "diamond"),
        ("oval", "en", "oval"),
        ("овальная форма", "ru", "oval"),
        ("prong setting", "en", "prong_setting"),
        ("крапановая закрепка", "ru", "prong_setting"),
        ("three stone", "en", "three_stone"),
        ("трёхкаменное кольцо", "ru", "three_stone"),
        ("platinum", "en", "platinum"),
        ("платина", "ru", "platinum"),
    )

    for term, locale, expected in cases:
        result = matcher.match(term, locale=locale)
        assert isinstance(result, ResolvedKnowledgeMatch)
        assert result.candidate.concept_id == expected


def test_production_catalog_preserves_shape_cut_boundaries():
    runtime, _ = _runtime()
    matcher = KnowledgeLibraryMatcher(runtime)

    shape = matcher.match("emerald cut", locale="en", context="stone_shape")
    cut = matcher.match("emerald cut", locale="en", context="stone_cut")

    assert isinstance(shape, ResolvedKnowledgeMatch)
    assert isinstance(cut, ResolvedKnowledgeMatch)
    assert shape.candidate.concept_id == "emerald_cut"
    assert cut.candidate.concept_id == "step_cut"


def test_production_catalog_policy_scope_covers_current_design_targets():
    runtime, _ = _runtime()
    targets = {policy.target for policy in runtime.policies}

    required = {
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
    }

    assert targets == required


def test_production_catalog_contains_no_quantitative_size_inference():
    runtime, _ = _runtime()
    forbidden = (
        "ct =",
        "carat equals",
        "mm per carat",
        "diameter from weight",
        "weight from diameter",
    )
    text = "\n".join(
        [claim.statement for claim in runtime.claims]
        + [policy.effect for policy in runtime.policies]
    ).casefold()

    assert all(token not in text for token in forbidden)
