import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from jewelai_domain.models import (
    Derived,
    Design,
    DesignRevision,
    Dimensions,
    Explicit,
    FinenessPurity,
    KaratPurity,
    Length,
    NotApplicable,
    StoneQuantity,
    Unknown,
    Weight,
    snapshot_json,
)
from jewelai_domain.schema import json_schema

SPEC = Path(__file__).resolve().parents[3] / "specs" / "jewelry-design-schema"
VALID = sorted((SPEC / "fixtures" / "valid").glob("*.json"))
INVALID = sorted((SPEC / "fixtures" / "invalid").glob("*.json"))


@pytest.fixture
def wire():
    return json.loads((SPEC / "fixtures" / "valid" / "ring.json").read_text())


@pytest.fixture
def validator():
    schema = json_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_committed_schema_matches_generator():
    committed = json.loads((SPEC / "schema.json").read_text())
    assert committed == json_schema()
    assert len(VALID) >= 4 and len(INVALID) >= 10


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_fixtures_round_trip(path, validator):
    text = path.read_text()
    validator.validate(json.loads(text))
    snapshot = DesignRevision.model_validate_json(text)
    serialized = snapshot_json(snapshot)
    validator.validate(json.loads(serialized))
    assert DesignRevision.model_validate_json(serialized) == snapshot


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_fixtures_rejected_by_both_contracts(path, validator):
    text = path.read_text()
    assert list(validator.iter_errors(json.loads(text)))
    with pytest.raises(ValidationError):
        DesignRevision.model_validate_json(text)


def test_absent_unknown_and_not_applicable_are_distinct(wire):
    empty = Design()
    assert empty.center_stone.shape is None
    data = deepcopy(wire["design"])
    data["center_stone"]["shape"] = {
        "availability": "unknown",
        "origin": "unknown",
        "requirement": "required",
    }
    unknown = Design.model_validate(data)
    assert isinstance(unknown.center_stone.shape, Unknown)
    assert unknown.center_stone.shape.requirement == "required"
    assert Unknown(requirement="optional") != unknown.center_stone.shape
    data["center_stone"]["shape"] = {
        "availability": "not_applicable",
        "reason": "No center stone in this design",
        "source": wire["event"]["source"],
    }
    na = Design.model_validate(data)
    assert isinstance(na.center_stone.shape, NotApplicable)
    assert na.center_stone.shape.reason
    assert empty != unknown != na


@pytest.mark.parametrize("number", [-1, 0, True, "3", float("inf"), float("nan")])
@pytest.mark.parametrize("kind", [Length, Weight])
def test_measurements_are_finite_positive_and_numeric(kind, number):
    with pytest.raises(ValidationError):
        kind(value=number)


@pytest.mark.parametrize("number", [-1, 0, 1.5, True, "4"])
def test_quantity_requires_positive_integer(number):
    with pytest.raises(ValidationError):
        StoneQuantity(value=number, scope="per_side")


def test_quantity_scope_preserved():
    quantity = StoneQuantity(value=4, scope="per_side")
    assert quantity.model_dump() == {"value": 4, "scope": "per_side"}
    with pytest.raises(ValidationError):
        StoneQuantity(value=4)


@pytest.mark.parametrize(
    "kind,value",
    [
        (KaratPurity, 25),
        (KaratPurity, 0),
        (FinenessPurity, 1001),
        (FinenessPurity, 0),
        (FinenessPurity, 750.5),
    ],
)
def test_metal_purity_bounds(kind, value):
    with pytest.raises(ValidationError):
        kind(value=value)


def test_schema_version_must_be_explicit(wire, validator):
    del wire["schema_version"]
    assert list(validator.iter_errors(wire))
    with pytest.raises(ValidationError):
        DesignRevision.model_validate(wire)


def test_derived_dimensions_require_versioned_source_and_uncertainty(wire):
    source = {
        "kind": "knowledge",
        "record_id": "test_only_geometry",
        "version": "1.0.0",
        "recorded_at": wire["created_at"],
    }
    dimensions = Dimensions(length=Length(value=8), width=Length(value=6), depth=Length(value=4))
    value = Derived[Dimensions](value=dimensions, sources=(source,), uncertainty="Synthetic test")
    assert value.sources[0].version == "1.0.0"
    for field in ("sources", "uncertainty"):
        data = value.model_dump()
        del data[field]
        with pytest.raises(ValidationError):
            Derived[Dimensions].model_validate(data)


def test_no_dimension_inference_from_weight(wire):
    snapshot = DesignRevision.model_validate(wire)
    assert snapshot.design.center_stone.weight.value.value == 3
    assert isinstance(snapshot.design.center_stone.dimensions, Unknown)


def test_shape_and_material_are_separate(wire):
    stone = DesignRevision.model_validate(wire).design.center_stone
    assert stone.material.value == "emerald"
    assert stone.shape.value == "oval"


def test_duplicate_group_ids_require_semantic_validation(wire):
    wire["design"]["side_stones"].append(deepcopy(wire["design"]["side_stones"][0]))
    with pytest.raises(ValidationError, match="group IDs"):
        DesignRevision.model_validate(wire)


def test_deep_immutability(wire):
    revision = DesignRevision.model_validate(wire)
    with pytest.raises(ValidationError, match="frozen"):
        revision.design.metal.color.value = "yellow"
    assert isinstance(revision.design.side_stones, tuple)
    with pytest.raises(TypeError):
        revision.design.side_stones[0] = revision.design.side_stones[0]


def test_revalidation_catches_unsafe_pydantic_copy(wire):
    revision = DesignRevision.model_validate(wire)
    unsafe = revision.model_copy(update={"revision": -1})
    with pytest.raises(ValidationError):
        snapshot_json(unsafe)


def test_nested_unsafe_copy_cannot_bypass_lock_invariant(wire):
    value = Explicit[str](value="gold", source=wire["event"]["source"])
    unsafe = value.model_copy(update={"locked": True})
    with pytest.raises(ValidationError):
        Explicit[str].model_validate(unsafe)


@pytest.mark.parametrize("mutation", ["self_parent", "future_source", "naive_timestamp"])
def test_lineage_semantics(wire, mutation):
    if mutation == "self_parent":
        wire.update(revision=2, parent_revision_id=wire["revision_id"])
        wire["event"]["action"] = "edit"
    elif mutation == "future_source":
        wire["event"]["source"]["recorded_at"] = "2030-01-01T00:00:00Z"
    else:
        wire["created_at"] = "2026-09-20T12:00:00"
    with pytest.raises(ValidationError):
        DesignRevision.model_validate(wire)
