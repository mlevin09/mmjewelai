"""Knowledge Library Contract 2.0 deterministic rules (ADR 0048; Architecture v1.2 §5, §7)."""

import json
from pathlib import Path

import pytest

from jewelai_domain.kb_contract import (
    ERROR_CODES,
    POLICY_REVISION_1,
    KnowledgeKbError,
    allowed_uses,
    apply_formula,
    canonical_json,
    canonical_number,
    contract_document,
    evaluate_profile,
    normalize_scope,
    normalize_term,
    normalize_value,
)

ROOT = Path(__file__).resolve().parents[3]


def test_published_contract_json_matches_the_code():
    published = json.loads(
        (ROOT / "specs/knowledge-library-kb/contract-2.0.0.json").read_text(encoding="utf-8")
    )
    assert published == contract_document()


def test_policy_revision_1_is_the_v162_matrix_and_prompt_is_never_automatic():
    prompt = {p.permission_code for p in POLICY_REVISION_1 if "prompt" in p.uses}
    assert prompt == {
        "FACT_DISPLAY_RENDER_HINT",
        "APPROX_SIZE_REFERENCE",
        "NONBINDING_UNIT_CONVERSION",
        "NONBINDING_PURITY_CONVERSION",
    }
    verified = [p for p in POLICY_REVISION_1 if p.allowed_status == "VERIFIED"]
    assert len(verified) == 10 and len(verified) > len(prompt)  # VERIFIED ≠ prompt
    assert not any({"validate_block", "validate_warn"} & set(p.uses) for p in POLICY_REVISION_1)
    assert allowed_uses("CARE_GUIDANCE_CONDITIONAL", "VERIFIED") == ("display", "explain")
    assert allowed_uses("GOST_ALLOY_DENSITY_REFERENCE", "VERIFIED") == (
        "display",
        "explain",
        "calc_reference",
    )
    assert "prompt" not in allowed_uses("RESEARCH_WITH_CAVEAT", "REFERENCE ONLY")
    assert allowed_uses("EXCLUDE", "REJECTED") == ()
    # Incompatible status grants nothing.
    assert allowed_uses("FACT_DISPLAY_RENDER_HINT", "REFERENCE ONLY") == ()


def test_scope_vocabulary_is_closed_and_canonical():
    scope, key = normalize_scope({"carat_weight": 1.50, "shape": " round ", "reference": "x"})
    assert scope == {"carat_weight": "1.5", "reference": "x", "shape": "round"}
    assert key == canonical_json(scope)
    assert normalize_scope({"shape": "round", "carat_weight": "1.5", "reference": "x"})[1] == key
    with pytest.raises(ValueError, match="unknown scope keys"):
        normalize_scope({"colour": "red"})
    with pytest.raises(ValueError):
        normalize_scope({"origin": True})


def test_values_are_typed_and_reject_formula_text():
    assert normalize_value({"num": "4.00"}, "number") == {"num": "4"}
    assert canonical_number(1.770) == "1.77"
    with pytest.raises(ValueError):
        normalize_value({"min": 2, "max": 1}, "range")
    with pytest.raises(ValueError):
        normalize_value({"text_ru": "=SUM(A1)"}, "text")
    with pytest.raises(ValueError):
        normalize_value({"num": float("nan")}, "number")
    with pytest.raises(ValueError):
        normalize_value({"num": 1, "unit": "mm"}, "number")


def test_mohs_is_ordinal_without_universal_tolerance():
    exact = evaluate_profile("ordinal_scale", {"precision": 1}, {"num": "9"}, "exact", {"num": "9"})
    assert exact[0] == "source_match"
    # A universal ±0.25 would have accepted 8.75; the ordinal profile does not.
    assert (
        evaluate_profile("ordinal_scale", {"precision": 2}, {"num": "8.75"}, "exact", {"num": "9"})[
            0
        ]
        == "mismatch"
    )
    narrower = evaluate_profile(
        "ordinal_scale", {}, {"num": "7"}, "exact", {"min": "6.5", "max": "7.5"}
    )
    assert narrower[0] == "within_range"


def test_ri_range_must_equal_the_source_range():
    source = {"min": "1.762", "max": "1.77"}
    assert evaluate_profile("source_range", {"precision": 3}, source, "source_range", source)[
        0
    ] == ("source_match")
    narrower = {"min": "1.763", "max": "1.769"}
    assert evaluate_profile("source_range", {"precision": 3}, narrower, "x", source)[0] == (
        "within_range"
    )
    assert evaluate_profile("source_range", {}, {"num": "1.5"}, "x", source)[0] == "mismatch"


def test_stuller_point_rules_allow_equal_diameters_and_reject_mixed_or_derived():
    point = {"num": "5"}
    for _weight in ("0.47", "0.48"):  # equal diameters for different weights are allowed
        assert evaluate_profile("approximate_point", {"precision": 1}, point, "approximate", point)[
            0
        ] == ("source_match")
    assert (
        evaluate_profile("approximate_point", {}, point, "derived", point)[0] == "derived_estimate"
    )
    mixed = {"min": "6.4", "max": "6.5"}
    assert evaluate_profile("approximate_point", {}, mixed, "approximate", {"num": "6.4"})[0] == (
        "mismatch"
    )
    assert evaluate_profile("approximate_point", {}, point, "exact", point)[0] == "mismatch"


@pytest.mark.parametrize(
    "diameter,us,eu,uk",
    [("15.0", "4", "47", "H"), ("15.3", "4.5", "48", "I"), ("18.1", "8", "57", "P")],
)
def test_ring_formulas_follow_ev_ring(diameter, us, eu, uk):
    assert apply_formula("ring_us_from_diameter", "nearest_half", diameter) == us
    assert apply_formula("ring_eu_from_diameter", "nearest_int", diameter) == eu
    assert apply_formula("ring_uk_from_diameter", "floor", diameter) == uk


def test_inconsistent_legacy_conversion_is_a_mismatch_not_a_tolerance():
    # v1.6.2 K-14293: 16.1 mm → EU 50, but π·16.1 = 50.58 → 51 under the ISO definition.
    outcome = evaluate_profile(
        "formula",
        {"formula": "ring_eu_from_diameter", "rounding": "nearest_int"},
        {"num": "50"},
        "derived",
        None,
        {"from_value": "16.1"},
    )
    assert outcome[0] == "mismatch"


def test_unsourced_attributes_never_match():
    for value in ({"num": "7"}, {"enum": "k14"}):
        assert evaluate_profile("manual_source_review", {}, value, "derived", value)[0] == (
            "no_source"
        )
    assert evaluate_profile("exact_number", {}, {"num": "1"}, "exact", None)[0] == "no_source"


def test_term_normalization_matches_dictionary_rules():
    assert normalize_term("  Карат  ") == "карат"
    assert normalize_term("CARAT") == normalize_term("carat")


def test_errors_are_typed():
    assert "payload_conflict" in ERROR_CODES
    assert KnowledgeKbError("no_data").code == "no_data"
    with pytest.raises(ValueError):
        KnowledgeKbError("something_else")
