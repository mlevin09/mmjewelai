import copy
import json
from pathlib import Path

import pytest

from jewelai_domain import (
    KnowledgeBaseValidationError,
    load_parametric_knowledge,
    validate_parametric_knowledge,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "knowledge-base" / "v1.0.0.json"


def _catalog():
    return load_parametric_knowledge(CATALOG)


def test_parametric_catalog_loads_and_is_deterministic():
    first = _catalog()
    second = _catalog()

    assert first == second
    assert first.catalog_id == "jewelai.production.parametric_gemstones"
    assert first.artifact_version == "1.0.0"
    assert len(first.sources) == 12
    assert len(first.specific_gravity) == 8
    assert len(first.calibrated_size_weight) == 564
    assert first.sha256 == second.sha256


def test_one_carat_round_diamond_retains_multiple_source_references():
    catalog = _catalog()
    records = [
        item
        for item in catalog.find_calibrations(material_id="diamond", shape_id="round")
        if item.weight_ct == 1.0
    ]

    by_source = {item.source_id: item for item in records}
    assert by_source["SRC-GEMSELECT-CALIBRATED"].dimensions_mm.diameter == 6.5
    assert by_source["SRC-STULLER-MM-CT"].dimensions_mm.diameter == 6.5
    assert by_source["SRC-OCTONUS-TOLKOWSKY"].dimensions_mm.diameter == 6.47
    assert by_source["SRC-OCTONUS-TOLKOWSKY"].dimensions_mm.depth == 4.0


def test_equal_dimensions_do_not_imply_equal_material_weight():
    catalog = _catalog()

    round_65 = {
        item.material_id: item.weight_ct
        for item in catalog.find_calibrations(shape_id="round")
        if item.dimensions_mm.diameter == 6.5
        and item.source_id == "SRC-GEMSELECT-CALIBRATED"
    }

    assert round_65["diamond"] == 1.0
    assert round_65["sapphire"] == 1.41
    assert round_65["opal"] == 0.75


def test_specific_gravity_is_source_backed_and_not_a_size_rule():
    catalog = _catalog()
    values = {item.material_id: item for item in catalog.specific_gravity}

    assert values["diamond"].nominal == 3.52
    assert values["ruby"].nominal == 4.0
    assert values["emerald"].nominal == 2.72
    assert values["opal"].nominal == 2.15

    assert all("not a size conversion" in item.applicability for item in values.values())


def test_unknown_source_reference_fails_closed():
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    broken = copy.deepcopy(raw)
    broken["calibrated_size_weight"][0]["source_id"] = "SRC-MISSING"

    with pytest.raises(KnowledgeBaseValidationError, match="unknown source"):
        validate_parametric_knowledge(broken)


def test_calibrated_record_cannot_claim_exact_measured_dimensions():
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    broken = copy.deepcopy(raw)
    broken["calibrated_size_weight"][0]["uncertainty"] = "Exact measured dimensions"

    with pytest.raises(KnowledgeBaseValidationError, match="cannot claim exact measured"):
        validate_parametric_knowledge(broken)


def test_geometry_requires_diameter_or_length_and_width():
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    broken = copy.deepcopy(raw)
    broken["calibrated_size_weight"][0]["dimensions_mm"] = {"length": 6.0}

    with pytest.raises(KnowledgeBaseValidationError, match="both length and width"):
        validate_parametric_knowledge(broken)
