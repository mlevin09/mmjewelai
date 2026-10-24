from pathlib import Path

from jewelai_domain import load_parametric_knowledge
from jewelai_domain.models import DesignRevision

from jewelai_api.parametric_enrichment import select_parametric_references

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
PARAMETRIC = ROOT / "data" / "knowledge-base" / "v1.0.0.json"


def _explicit(revision, value):
    return {
        "availability": "value",
        "value": value,
        "confirmed": True,
        "locked": False,
        "origin": "explicit",
        "source": revision.event.source.model_dump(mode="json"),
    }


def _diamond_round(revision, *, weight_ct=1.0, dimensions=None):
    payload = revision.model_dump(mode="json")
    stone = payload["design"]["center_stone"]
    stone["material"] = _explicit(revision, "diamond")
    stone["shape"] = _explicit(revision, "round")
    stone["weight"] = _explicit(revision, {"value": weight_ct, "unit": "ct"})
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
