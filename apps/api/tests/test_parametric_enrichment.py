from pathlib import Path

import pytest
from jewelai_domain import load_parametric_knowledge
from jewelai_domain.models import DesignRevision

from jewelai_api.parametric_enrichment import select_parametric_references

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
PARAMETRIC = ROOT / "data" / "knowledge-base" / "v1.0.0.json"


def _explicit(revision, value, *, confirmed=True):
    return {
        "availability": "value",
        "value": value,
        "confirmed": confirmed,
        "locked": False,
        "origin": "explicit",
        "source": revision.event.source.model_dump(mode="json"),
    }


def _derived(revision, value, *, confirmed):
    return {
        "availability": "value",
        "value": value,
        "confirmed": confirmed,
        "locked": False,
        "origin": "derived",
        "sources": [
            {
                "kind": "knowledge",
                "record_id": "CAL-DIAMOND-ROUND-1-42",
                "version": "1.0.0",
                "recorded_at": revision.event.source.recorded_at.isoformat(),
            }
        ],
        "uncertainty": "Source-backed calibration; user acceptance is explicit.",
    }


def _assumed(revision, value, *, confirmed=False):
    return {
        "availability": "value",
        "value": value,
        "confirmed": confirmed,
        "locked": False,
        "origin": "assumed",
        "source": {
            "kind": "rule",
            "rule_id": "R-TEST-ASSUMPTION",
            "version": "1.0.0",
            "recorded_at": revision.event.source.recorded_at.isoformat(),
        },
        "rationale": "Test-only visualization assumption.",
    }


def _diamond_round(
    revision,
    *,
    weight_ct=1.0,
    dimensions=None,
    material=None,
    shape=None,
    weight=None,
):
    payload = revision.model_dump(mode="json")
    stone = payload["design"]["center_stone"]
    stone["material"] = material or _explicit(revision, "diamond")
    stone["shape"] = shape or _explicit(revision, "round")
    stone["weight"] = weight or _explicit(revision, {"value": weight_ct, "unit": "ct"})
    stone["dimensions"] = dimensions or {
        "availability": "unknown",
        "origin": "unknown",
        "requirement": "undetermined",
        "value": None,
        "confirmed": False,
        "locked": False,
    }
    return DesignRevision.model_validate(payload)


def test_exact_one_carat_round_diamond_reference_is_deduplicated_across_sources():
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)

    references = select_parametric_references(_diamond_round(revision), catalog)

    assert len(references) == 1
    reference = references[0]
    assert reference.target == "center_stone.dimensions"
    assert reference.material_id == "diamond"
    assert reference.shape_id == "round"
    assert reference.weight_ct == 1.0
    assert reference.estimate_kind == "APPROXIMATE_CALIBRATION"
    assert reference.dimensions.diameter_mm == 6.5
    assert reference.dimensions.depth_mm is None
    assert reference.source_ids == (
        "SRC-GEMSELECT-CALIBRATED",
        "SRC-STULLER-MM-CT",
    )
    assert len(reference.record_ids) == 2
    assert "SRC-OCTONUS-TOLKOWSKY" not in reference.source_ids


def test_unconfirmed_explicit_user_context_remains_eligible():
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)
    candidate = _diamond_round(
        revision,
        material=_explicit(revision, "diamond", confirmed=False),
        shape=_explicit(revision, "round", confirmed=False),
        weight=_explicit(revision, {"value": 1.0, "unit": "ct"}, confirmed=False),
    )

    assert len(select_parametric_references(candidate, catalog)) == 1


def test_selector_never_interpolates_or_rounds_weight():
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)

    assert (
        select_parametric_references(
            _diamond_round(revision, weight_ct=0.99),
            catalog,
        )
        == ()
    )
    assert (
        select_parametric_references(
            _diamond_round(revision, weight_ct=1.01),
            catalog,
        )
        == ()
    )


def test_authoritative_dimensions_suppress_parametric_reference():
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)
    dimensions = _explicit(
        revision,
        {
            "length": {"value": 6.4, "unit": "mm"},
            "width": {"value": 6.4, "unit": "mm"},
            "depth": {"value": 4.0, "unit": "mm"},
        },
    )

    assert (
        select_parametric_references(
            _diamond_round(revision, dimensions=dimensions),
            catalog,
        )
        == ()
    )


def test_not_applicable_dimensions_suppress_parametric_reference_deterministically():
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)
    dimensions = {
        "availability": "not_applicable",
        "origin": "explicit",
        "value": None,
        "reason": "The user explicitly excluded dimensional guidance.",
        "source": revision.event.source.model_dump(mode="json"),
        "confirmed": True,
        "locked": False,
    }
    candidate = _diamond_round(revision, dimensions=dimensions)

    assert select_parametric_references(candidate, catalog) == ()
    assert select_parametric_references(candidate, catalog) == ()


@pytest.mark.parametrize("assumed_target", ["material", "shape", "weight", "all"])
def test_unconfirmed_assumptions_are_ineligible_parametric_context(assumed_target):
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)
    values = {
        "material": _explicit(revision, "diamond"),
        "shape": _explicit(revision, "round"),
        "weight": _explicit(revision, {"value": 1.0, "unit": "ct"}),
    }
    targets = values if assumed_target == "all" else {assumed_target: values[assumed_target]}
    for target in targets:
        raw = "diamond" if target == "material" else "round"
        if target == "weight":
            raw = {"value": 1.0, "unit": "ct"}
        values[target] = _assumed(revision, raw)

    candidate = _diamond_round(revision, **values)
    assert select_parametric_references(candidate, catalog) == ()


def test_unconfirmed_derived_value_is_ineligible_but_confirmed_value_is_eligible():
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)

    unaccepted = _diamond_round(
        revision,
        material=_derived(revision, "diamond", confirmed=False),
    )
    accepted = _diamond_round(
        revision,
        material=_derived(revision, "diamond", confirmed=True),
        shape=_assumed(revision, "round", confirmed=True),
        weight=_derived(revision, {"value": 1.0, "unit": "ct"}, confirmed=True),
    )

    assert select_parametric_references(unaccepted, catalog) == ()
    assert len(select_parametric_references(accepted, catalog)) == 1


@pytest.mark.parametrize("missing_target", ["material", "shape", "weight"])
def test_missing_required_context_is_ineligible(missing_target):
    revision = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    catalog = load_parametric_knowledge(PARAMETRIC)
    missing = {
        "availability": "unknown",
        "origin": "unknown",
        "requirement": "undetermined",
        "value": None,
        "confirmed": False,
        "locked": False,
    }

    assert (
        select_parametric_references(
            _diamond_round(revision, **{missing_target: missing}),
            catalog,
        )
        == ()
    )
