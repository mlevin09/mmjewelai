"""PCAP: separate IFP capacity, exact version readers, and frozen 2.0 retention."""

import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_downstream_preparation import prepare, stage
from test_final_prompt import _assemble
from test_final_prompt import dictionary as dictionary
from test_final_prompt import ring as ring
from test_final_prompt import runtime as runtime
from test_final_prompt import templates as templates

from jewelai_prompts import (
    CanonicalFinalPromptAssemblyV2_1,
    CanonicalInternalFinalPrompt,
    CanonicalInternalFinalPromptHandoff,
    CanonicalInternalFinalPromptV2_1,
    GenerationPreparation,
    GenerationPreparationError,
    build_internal_final_prompt_handoff,
    decode_canonical_handoff,
    decode_canonical_internal_final_prompt,
)
from jewelai_prompts.downstream_preparation import (
    canonical_bytes,
    check_ifp_v2_1_capacity,
    render_canonical_source_text,
    source_content_hash,
)
from jewelai_prompts.final_prompt import FinalPromptConstraint, _check_current_text_capacity


def boundary_payload(prompt, characters, character="A"):
    """Synthetic validator boundary only; not a professional/source qualification claim."""
    payload = prompt.model_dump(mode="json", exclude={"content_hash"})
    payload["constraints"][0]["instruction"] = ""

    def render():
        unchecked = prompt.model_copy(
            update={
                "constraints": tuple(FinalPromptConstraint(**c) for c in payload["constraints"])
            }
        )
        return render_canonical_source_text(unchecked)

    payload["constraints"][0]["instruction"] = character * (characters - len(render()))
    payload["prompt_text"] = render()
    assert len(payload["prompt_text"]) == characters
    payload["content_hash"] = source_content_hash(payload)
    return payload


def test_exact_32000_accepts_complete_render_and_32001_rejects(
    ring, templates, runtime, dictionary
):
    assembly = _assemble(ring, templates, runtime, dictionary)
    prompt = assembly.internal_final_prompt
    payload = boundary_payload(prompt, 32_000)
    accepted = CanonicalInternalFinalPromptV2_1.model_validate(payload)
    assert accepted.prompt_text == payload["prompt_text"]
    handoff = build_internal_final_prompt_handoff(
        CanonicalFinalPromptAssemblyV2_1(
            description=assembly.description, internal_final_prompt=accepted
        )
    )
    assert decode_canonical_handoff(handoff.model_dump_json()) == handoff
    assert len(handoff.internal_final_prompt.prompt_text) == 32_000
    with pytest.raises(ValueError, match="preparation_capacity_exceeded"):
        CanonicalInternalFinalPromptV2_1.model_validate(boundary_payload(prompt, 32_001))


def test_utf8_policy_independent_of_character_policy(
    monkeypatch, ring, templates, runtime, dictionary
):
    import jewelai_prompts.downstream_preparation as module

    check_ifp_v2_1_capacity("\U0001f600" * 32_000)  # Exactly 128,000 bytes.
    with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
        check_ifp_v2_1_capacity("\U0001f600" * 32_000 + "A")
    prompt = _assemble(ring, templates, runtime, dictionary).internal_final_prompt
    payload = boundary_payload(prompt, 25_000, "Ж")
    byte_count = len(payload["prompt_text"].encode("utf-8"))
    assert 32_000 < byte_count < 128_000
    monkeypatch.setattr(module, "IFP_V2_1_MAX_BYTES", byte_count)
    assert (
        CanonicalInternalFinalPromptV2_1.model_validate(payload).prompt_text
        == payload["prompt_text"]
    )
    monkeypatch.setattr(module, "IFP_V2_1_MAX_BYTES", byte_count - 1)
    with pytest.raises(ValueError, match="preparation_capacity_exceeded"):
        CanonicalInternalFinalPromptV2_1.model_validate(payload)


@pytest.mark.parametrize("version", ["2.0.0", "2.1.0"])
def test_versioned_readers_and_preparation_preserve_original_bytes(
    ring, templates, runtime, dictionary, version
):
    # Existing text-only fixture adaptation; image transport is not part of PCAP.
    data = ring.model_dump(mode="json")
    data["design"]["references"]["value"] = []
    ring = type(ring).model_validate(data)
    assembly = _assemble(ring, templates, runtime, dictionary)
    source = (
        stage(assembly, ring)
        if version == "2.0.0"
        else build_internal_final_prompt_handoff(assembly)
    )
    raw = source.model_dump_json()
    decoded = decode_canonical_handoff(raw)
    assert decoded.schema_version == version
    assert decoded.model_dump_json() == raw
    assert (
        decode_canonical_internal_final_prompt(decoded.internal_final_prompt.model_dump_json())
        == decoded.internal_final_prompt
    )
    artifact = prepare(decoded, ring)
    assert GenerationPreparation(artifact.canonical).canonical == artifact.canonical
    assert canonical_bytes(artifact.payload.source_handoff) == canonical_bytes(source)
    assert (
        prepare(stage(assembly, ring), ring).payload.execution
        == prepare(build_internal_final_prompt_handoff(assembly), ring).payload.execution
    )
    assert (
        build_internal_final_prompt_handoff(assembly).model_dump_json()
        == build_internal_final_prompt_handoff(assembly).model_dump_json()
    )
    if version == "2.0.0":
        changed = boundary_payload(assembly.internal_final_prompt, 25_000)
        changed["schema_version"] = "2.0.0"
        changed["prompt_text"] = changed["prompt_text"].replace("2.1.0", "2.0.0", 1)
        changed["content_hash"] = source_content_hash(
            {k: v for k, v in changed.items() if k != "content_hash"}
        )
        with pytest.raises(ValidationError, match="20000"):
            CanonicalInternalFinalPrompt.model_validate(changed)


@pytest.mark.parametrize(
    "mutation",
    ["missing_version", "missing_inner_version", "unsupported", "mixed", "hash", "payload"],
)
def test_strict_handoff_dispatch_rejects_tamper(ring, templates, runtime, dictionary, mutation):
    source = build_internal_final_prompt_handoff(_assemble(ring, templates, runtime, dictionary))
    value = deepcopy(source.model_dump(mode="json"))
    if mutation == "missing_version":
        del value["schema_version"]
    elif mutation == "missing_inner_version":
        del value["internal_final_prompt"]["schema_version"]
    elif mutation == "unsupported":
        value["schema_version"] = "2.2.0"
    elif mutation == "mixed":
        value["internal_final_prompt"]["schema_version"] = "2.0.0"
    elif mutation == "hash":
        value["content_hash"] = "0" * 64
    else:
        value["internal_final_prompt"]["prompt_text"] += "changed"
    with pytest.raises(ValueError):
        decode_canonical_handoff(value)


def test_description_and_execution_limits_do_not_inherit_ifp_capacity():
    import jewelai_prompts.downstream_preparation as module

    assert (module.RENDER_MAX_CHARACTERS, module.RENDER_MAX_BYTES) == (20_000, 80_000)
    assert (module.SOURCE_MAX_BYTES, module.ARTIFACT_MAX_BYTES) == (1_048_576, 2_097_152)
    assert (module.IFP_V2_1_MAX_CHARACTERS, module.IFP_V2_1_MAX_BYTES) == (32_000, 128_000)
    with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
        _check_current_text_capacity("A" * 20_001)


@pytest.mark.parametrize(
    "model,expected",
    [
        (
            CanonicalInternalFinalPrompt,
            "69e861fd74f004c33b05d97027659c757bd641d02f81429bb2d62c710e75ed62",
        ),
        (
            CanonicalInternalFinalPromptHandoff,
            "9ef088e6252efa5a3980ab2a7390cd3ddb1aaa86ab7305cd14c784fed500aed1",
        ),
    ],
)
def test_frozen_v2_schema_fingerprints_from_ad7de376(model, expected):
    raw = json.dumps(
        model.model_json_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert hashlib.sha256(raw.encode()).hexdigest() == expected
