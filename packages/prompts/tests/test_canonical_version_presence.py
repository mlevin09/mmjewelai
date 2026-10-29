"""R1: raw versions must exist before model defaults; typed legacy callers stay valid."""

import json
from copy import deepcopy
from itertools import product

import pytest
from test_downstream_preparation import CREATED_AT, PREPARATION_ID, gate_for, prepare, stage
from test_downstream_preparation import ring as ring
from test_final_prompt import _assemble
from test_final_prompt import dictionary as dictionary
from test_final_prompt import runtime as runtime
from test_final_prompt import templates as templates

from jewelai_prompts import (
    CanonicalInternalFinalPrompt,
    CanonicalInternalFinalPromptHandoff,
    GenerationPreparation,
    GenerationPreparationError,
    PreparationErrorCode,
    build_generation_preparation,
    build_internal_final_prompt_handoff,
    decode_canonical_handoff,
    decode_canonical_internal_final_prompt,
)
from jewelai_prompts.downstream_preparation import render_semantic_source

VERSIONS = ("2.0.0", "2.1.0")
REPRESENTATIONS = ("dict", "json", "bytes")
VERSION_FIELDS = ("schema_version", "internal_final_prompt_schema_version", "nested")


@pytest.fixture(params=VERSIONS)
def source(request, ring, templates, runtime, dictionary):
    assembly = _assemble(ring, templates, runtime, dictionary)
    return (
        stage(assembly, ring)
        if request.param == "2.0.0"
        else build_internal_final_prompt_handoff(assembly)
    )


def wire(value, representation):
    if representation == "dict":
        return value
    text = json.dumps(value, ensure_ascii=False)
    return text if representation == "json" else text.encode("utf-8")


def version_location(value, field):
    return (
        (value["internal_final_prompt"], "schema_version") if field == "nested" else (value, field)
    )


@pytest.mark.parametrize("representation", REPRESENTATIONS)
@pytest.mark.parametrize("field", VERSION_FIELDS)
def test_missing_handoff_version_rejected_before_defaults(source, field, representation):
    value = source.model_dump(mode="json")
    location, key = version_location(value, field)
    del location[key]
    with pytest.raises(GenerationPreparationError, match="invalid_preparation_source"):
        decode_canonical_handoff(wire(value, representation))


@pytest.mark.parametrize("representation", REPRESENTATIONS)
def test_missing_standalone_ifp_version_rejected(source, representation):
    value = source.internal_final_prompt.model_dump(mode="json")
    del value["schema_version"]
    with pytest.raises(GenerationPreparationError, match="invalid_preparation_source"):
        decode_canonical_internal_final_prompt(wire(value, representation))


@pytest.mark.parametrize("representation", REPRESENTATIONS)
@pytest.mark.parametrize("field", VERSION_FIELDS)
@pytest.mark.parametrize("invalid", [None, "2.2.0", 2, True, [], {}])
def test_invalid_handoff_versions_fail_closed(source, field, invalid, representation):
    value = source.model_dump(mode="json")
    location, key = version_location(value, field)
    location[key] = invalid
    with pytest.raises(GenerationPreparationError, match="invalid_preparation_source"):
        decode_canonical_handoff(wire(value, representation))


@pytest.mark.parametrize("representation", REPRESENTATIONS)
@pytest.mark.parametrize("invalid", [None, "2.2.0", 2, True, [], {}])
def test_invalid_standalone_versions_fail_closed(source, invalid, representation):
    value = source.internal_final_prompt.model_dump(mode="json")
    value["schema_version"] = invalid
    with pytest.raises(GenerationPreparationError, match="invalid_preparation_source"):
        decode_canonical_internal_final_prompt(wire(value, representation))


@pytest.mark.parametrize("representation", REPRESENTATIONS)
@pytest.mark.parametrize("versions", [v for v in product(VERSIONS, repeat=3) if len(set(v)) != 1])
def test_mixed_handoff_versions_rejected_before_payload_validation(
    source, versions, representation
):
    value = source.model_dump(mode="json")
    for field, version in zip(VERSION_FIELDS, versions, strict=True):
        location, key = version_location(value, field)
        location[key] = version
    with pytest.raises(GenerationPreparationError, match="invalid_preparation_source"):
        decode_canonical_handoff(wire(value, representation))


@pytest.mark.parametrize("representation", (*REPRESENTATIONS, "typed"))
def test_valid_wire_and_typed_roundtrip_preserves_bytes_hashes_and_preparation(
    source, ring, representation
):
    raw = source.model_dump(mode="json")
    before = deepcopy(raw)
    decoded = decode_canonical_handoff(
        source if representation == "typed" else wire(raw, representation)
    )
    assert decoded.model_dump_json() == source.model_dump_json()
    assert raw == before  # The guard must not add fields or rewrite input.
    prompt = source.internal_final_prompt
    assert (
        decode_canonical_internal_final_prompt(
            prompt
            if representation == "typed"
            else wire(prompt.model_dump(mode="json"), representation)
        ).model_dump_json()
        == prompt.model_dump_json()
    )
    original = prepare(source, ring)
    assert prepare(decoded, ring).canonical == original.canonical
    assert GenerationPreparation(original.canonical).canonical == original.canonical


def test_historical_typed_default_construction_remains_compatible(
    ring, templates, runtime, dictionary
):
    source = stage(_assemble(ring, templates, runtime, dictionary), ring)
    payload = source.model_dump(mode="json")
    del payload["schema_version"]
    del payload["internal_final_prompt_schema_version"]
    prompt = payload["internal_final_prompt"]
    del prompt["schema_version"]
    typed_prompt = CanonicalInternalFinalPrompt.model_validate(prompt)
    assert "schema_version" not in typed_prompt.model_fields_set
    payload["internal_final_prompt"] = typed_prompt
    typed_source = CanonicalInternalFinalPromptHandoff.model_validate(payload)
    assert "schema_version" not in typed_source.model_fields_set
    assert "internal_final_prompt_schema_version" not in typed_source.model_fields_set
    assert decode_canonical_handoff(typed_source).model_dump_json() == source.model_dump_json()
    assert decode_canonical_internal_final_prompt(typed_prompt) == source.internal_final_prompt


@pytest.mark.parametrize("field", VERSION_FIELDS)
@pytest.mark.parametrize("representation", REPRESENTATIONS)
def test_downstream_consumers_reject_raw_missing_versions(source, ring, field, representation):
    value = source.model_dump(mode="json")
    location, key = version_location(value, field)
    del location[key]
    value = wire(value, representation)
    gate = gate_for(source, ring)
    for consume in (
        lambda: render_semantic_source(value, gate),
        lambda: build_generation_preparation(
            value, gate, preparation_id=PREPARATION_ID, created_at=CREATED_AT
        ),
    ):
        with pytest.raises(GenerationPreparationError) as error:
            consume()
        assert error.value.code == PreparationErrorCode.INVALID_SOURCE
